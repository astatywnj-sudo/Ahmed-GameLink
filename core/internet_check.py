"""Internet-up probe — the FIRST step of diagnostics (Spec §5).

If this fails, the report must say "no internet connection at all" and
the engine must stop (no nonsense "solutions"). Uses the well-known
generate_204 probe: HTTP 204 with no body, minimal bytes on metered
connections. Every byte is counted by the shared counter.
"""

import time

from core import config
from core.data_counter import DataCounter
from core.http_client import http_request


class InternetResult:
    __slots__ = ("ok", "status", "elapsed_ms", "error")

    def __init__(self, *, ok: bool, status: int = 0, elapsed_ms: float = 0.0,
                 error: str = "") -> None:
        self.ok = ok
        self.status = status
        self.elapsed_ms = elapsed_ms
        self.error = error


def check_internet(counter: DataCounter, *, timeout: float = None,
                   cancel=None) -> InternetResult:
    timeout = timeout or config.CHECK_TIMEOUT_SECONDS
    start = time.perf_counter()
    result = http_request("GET", config.INTERNET_PROBE_URL, counter=counter,
                          timeout=timeout, max_body=1024, cancel=cancel)
    elapsed_ms = (time.perf_counter() - start) * 1000.0
    if not result.ok:
        return InternetResult(ok=False, elapsed_ms=elapsed_ms, error=result.error)
    if 200 <= result.status < 205:
        return InternetResult(ok=True, status=result.status, elapsed_ms=elapsed_ms)
    return InternetResult(ok=False, status=result.status, elapsed_ms=elapsed_ms,
                          error=f"unexpected_status_{result.status}")
