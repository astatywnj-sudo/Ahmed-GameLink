"""HTTP(S) client built on http.client + CountingSocket.

Why not `requests`: it hides its sockets, so exact byte accounting
(Spec §8.3 — the project's top priority) would be impossible. Here every
request/response byte is measured by the counting wrapper.

- Follows redirects (each hop's bytes are counted).
- Body capped at `max_body` (default 64 KB) to keep diagnostics cheap —
  this is a diagnostics probe, not a downloader.
- Overall deadline enforced (Spec §5: 10 s cap per check).
"""

import http.client
import socket
import ssl
import time
import urllib.parse

from core.counting_socket import counting_connect
from core.data_counter import DataCounter
from core.tls_socket import tls_connect

USER_AGENT = "AhmedGameLink/0.1 (network diagnostics)"

# Errors mapped to short machine-readable reasons used later by the report.
_ERROR_REASONS = {
    socket.timeout: "timeout",
    TimeoutError: "timeout",
    ConnectionRefusedError: "refused",
    ConnectionResetError: "reset",
    ConnectionAbortedError: "aborted",
    socket.gaierror: "dns_resolution_failed",
    ssl.SSLCertVerificationError: "certificate_verification_failed",
}


def _error_reason(exc: BaseException) -> str:
    for cls, reason in _ERROR_REASONS.items():
        if isinstance(exc, cls):
            return reason
    return type(exc).__name__.lower()


class HttpResult:
    __slots__ = ("ok", "status", "reason_phrase", "final_url", "body",
                 "elapsed_ms", "truncated", "error", "redirects")

    def __init__(self, *, ok: bool, status: int = 0, reason_phrase: str = "",
                 final_url: str = "", body: bytes = b"", elapsed_ms: float = 0.0,
                 truncated: bool = False, error: str = "", redirects: int = 0) -> None:
        self.ok = ok
        self.status = status
        self.reason_phrase = reason_phrase
        self.final_url = final_url
        self.body = body
        self.elapsed_ms = elapsed_ms
        self.truncated = truncated
        self.error = error
        self.redirects = redirects


class _CountingHTTPConnection(http.client.HTTPConnection):
    def __init__(self, host: str, port: int, timeout: float, counter: DataCounter,
                 cancel=None) -> None:
        super().__init__(host, port, timeout=timeout)
        self._counter = counter
        self._cancel = cancel

    def connect(self) -> None:
        self.sock = counting_connect((self.host, self.port), timeout=self.timeout,
                                     counter=self._counter, cancel=self._cancel)
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)


class _CountingHTTPSConnection(_CountingHTTPConnection):
    default_port = 443

    def __init__(self, host: str, port: int, timeout: float, counter: DataCounter,
                 cancel=None) -> None:
        super().__init__(host, port, timeout, counter, cancel)
        self._tls_context = ssl.create_default_context()

    def connect(self) -> None:
        # TlsSocket routes EVERY encrypted byte through CountingSocket
        # (see core/tls_socket.py — wrap_socket would bypass counting).
        self.sock = tls_connect((self.host, self.port or 443), self.host,
                                min(self.timeout or 30, 60), self._counter,
                                self._tls_context, cancel=self._cancel)


def _build_connection(url: urllib.parse.ParseResult, timeout: float,
                      counter: DataCounter, cancel=None) -> http.client.HTTPConnection:
    if url.scheme == "https":
        return _CountingHTTPSConnection(url.hostname, url.port or 443, timeout,
                                        counter, cancel)
    if url.scheme == "http":
        return _CountingHTTPConnection(url.hostname, url.port or 80, timeout,
                                       counter, cancel)
    raise ValueError(f"unsupported URL scheme: {url.scheme!r}")


def http_request(method: str, url: str, *, counter: DataCounter,
                 timeout: float = 10.0, max_body: int = 64 * 1024,
                 max_redirects: int = 3, extra_headers: dict | None = None,
                 body: bytes | None = None,
                 cancel=None) -> HttpResult:
    deadline = time.monotonic() + timeout
    redirects = 0
    final_url = url

    try:
        while True:
            if cancel is not None:
                cancel.check()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return HttpResult(ok=False, final_url=final_url,
                                  error="timeout", redirects=redirects)
            parsed = urllib.parse.urlsplit(final_url)
            if not parsed.hostname:
                return HttpResult(ok=False, final_url=final_url,
                                  error="invalid_url", redirects=redirects)

            conn = _build_connection(parsed, min(remaining, timeout), counter, cancel)
            try:
                headers = {"User-Agent": USER_AGENT, "Accept-Encoding": "identity"}
                if extra_headers:
                    headers.update(extra_headers)
                target = urllib.parse.urlunsplit(("", "", parsed.path or "/",
                                                  parsed.query, ""))
                conn.request(method, target, body=body, headers=headers)
                resp = conn.getresponse()

                status = resp.status
                reason_phrase = resp.reason or ""
                chunks: list[bytes] = []
                received = 0
                truncated = False
                while received < max_body:
                    chunk = resp.read(8192)
                    if not chunk:
                        break
                    chunks.append(chunk)
                    received += len(chunk)
                else:
                    truncated = True
                resp_body = b"".join(chunks)

                if status in (301, 302, 303, 307, 308) and redirects < max_redirects:
                    location = resp.headers.get("Location", "")
                    resp.read()  # drain (counted) so the connection is reusable/clean
                    conn.close()
                    redirects += 1
                    final_url = urllib.parse.urljoin(final_url, location)
                    if method == "POST" and status in (301, 302, 303):
                        method = "GET"
                    continue

                conn.close()
                return HttpResult(ok=True, status=status, reason_phrase=reason_phrase,
                                  final_url=final_url, body=resp_body,
                                  elapsed_ms=0.0, truncated=truncated,
                                  redirects=redirects)
            finally:
                # Defensive: never leak a socket, even on exception paths.
                try:
                    conn.close()
                except OSError:
                    pass
    except OSError as exc:
        reason = "cancelled" if (cancel is not None and cancel.is_cancelled()) \
            else _error_reason(exc)
        return HttpResult(ok=False, final_url=final_url,
                          error=reason, redirects=redirects)
    except (http.client.HTTPException, ValueError) as exc:
        reason = "cancelled" if (cancel is not None and cancel.is_cancelled()) \
            else _error_reason(exc)
        return HttpResult(ok=False, final_url=final_url,
                          error=reason, redirects=redirects)


def measure_elapsed(fn, *args, **kwargs):
    """Small helper so callers get honest elapsed_ms around a single call."""
    start = time.perf_counter()
    result = fn(*args, **kwargs)
    result.elapsed_ms = (time.perf_counter() - start) * 1000.0
    return result
