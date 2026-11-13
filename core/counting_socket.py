"""CountingSocket — the exact-byte accounting layer.

Wraps a real socket and counts every byte through send()/recv() (and the
recv_into/makefile paths used by http.client). Because SSL wrapping
(ssl.wrap_socket) performs TLS I/O by calling the wrapped object's
send()/recv() methods, the bytes counted here are the REAL encrypted
bytes on the wire — including TLS handshake and record overhead.

Design constraints honoured:
- No packet capture drivers, no admin rights (Spec §6).
- send() delegates to the underlying sendall so partial-send
  under/over-counting can never happen.
"""

import io
import select
import socket
import threading
import time

from core.cancel import CancelContext, OperationCancelled
from core.data_counter import DataCounter


class CountingSocket:
    """TCP socket wrapper. Exposes the full interface used by http.client
    and ssl.wrap_socket (fileno, timeouts, options, family/type/proto)."""

    def __init__(self, sock: socket.socket, counter: DataCounter) -> None:
        self._sock = sock
        self._counter = counter

    # ------------------------------------------------------------ counting
    def send(self, data, flags: int = 0) -> int:
        # sendall guarantees the whole buffer crossed; count exactly once.
        self._sock.sendall(data)
        self._counter.add_sent(len(data))
        return len(data)

    def sendall(self, data, flags: int = 0) -> None:
        self._sock.sendall(data)
        self._counter.add_sent(len(data))

    def recv(self, bufsize: int, flags: int = 0) -> bytes:
        data = self._sock.recv(bufsize, flags)
        self._counter.add_received(len(data))
        return data

    def recv_into(self, buffer, nbytes: int = 0) -> int:
        n = self._sock.recv_into(buffer, nbytes or len(buffer))
        self._counter.add_received(n)
        return n

    # ------------------------------------------------------- makefile path
    def makefile(self, mode: str, buffering: int = -1, **kwargs):
        if "r" not in mode:
            raise NotImplementedError("CountingSocket.makefile supports read modes only")
        raw = _CountingRawReader(self._sock, self._counter)
        return io.BufferedReader(raw, buffer_size=max(buffering, 8192) if buffering > 0 else 8192)

    # ---------------------------------------------------------- forwarding
    def settimeout(self, value) -> None:
        self._sock.settimeout(value)

    def gettimeout(self):
        return self._sock.gettimeout()

    def setblocking(self, flag: bool) -> None:
        self._sock.setblocking(flag)

    def fileno(self) -> int:
        return self._sock.fileno()

    def setsockopt(self, level, optname, value) -> None:
        self._sock.setsockopt(level, optname, value)

    def getsockopt(self, level, optname):
        return self._sock.getsockopt(level, optname)

    def shutdown(self, how) -> None:
        self._sock.shutdown(how)

    def close(self) -> None:
        self._sock.close()

    @property
    def family(self) -> socket.AddressFamily:
        return self._sock.family

    @property
    def type(self) -> socket.SocketKind:
        return self._sock.type

    @property
    def proto(self) -> int:
        return self._sock.proto

    @property
    def underlying(self) -> socket.socket:
        """Escape hatch for callers that must touch the raw socket
        (used only by tests and shutdown logic)."""
        return self._sock


class _CountingRawReader(io.RawIOBase):
    """Raw reader for makefile('rb'): http.client reads HTTP responses
    through it, so plain-HTTP bytes are counted with the same exactness
    as TLS bytes."""

    def __init__(self, sock: socket.socket, counter: DataCounter) -> None:
        self._sock = sock
        self._counter = counter
        self._closed = False

    def readable(self) -> bool:
        return True

    def readinto(self, b) -> int:
        if self._closed:
            return 0
        try:
            data = self._sock.recv(len(b))
        except OSError:
            self._closed = True
            return 0
        if not data:
            self._closed = True
            return 0
        self._counter.add_received(len(data))
        n = min(len(data), len(b))
        b[:n] = data[:n]
        return n

    def close(self) -> None:
        self._closed = True
        io.RawIOBase.close(self)


class CountingUDPSocket:
    """UDP wrapper for DNS queries: counts sendto/recvfrom payloads
    exactly (the DNS wire bytes). IP/UDP frame headers are not visible
    at the socket API — documented constant gap, same policy as TCP."""

    def __init__(self, family: int, kind: int, counter: DataCounter) -> None:
        self._sock = socket.socket(family, kind)
        self._counter = counter

    def settimeout(self, value) -> None:
        self._sock.settimeout(value)

    def sendto(self, data, address) -> int:
        self._sock.sendto(data, address)
        self._counter.add_sent(len(data))
        return len(data)

    def recvfrom(self, bufsize: int):
        data, addr = self._sock.recvfrom(bufsize)
        self._counter.add_received(len(data))
        return data, addr

    def close(self) -> None:
        self._sock.close()


def counting_connect(address, *, timeout: float, counter: DataCounter,
                     cancel: CancelContext | None = None) -> CountingSocket:
    """socket.create_connection equivalent that returns a counting wrapper.

    With a CancelContext, the TCP connect is cancellable: a non-blocking
    connect + select loop checks the flag every 100 ms, so Cancel breaks
    a stuck connect almost instantly (getaddrinfo itself is an OS call
    and is bounded by the resolver timeout — documented limit).
    """
    if cancel is None:
        real = socket.create_connection(address, timeout=timeout)
        return CountingSocket(real, counter)

    host, port = address
    deadline = time.monotonic() + timeout
    last_error: OSError | None = None
    for family, stype, proto, _canon, sockaddr in socket.getaddrinfo(
            host, port, 0, socket.SOCK_STREAM):
        real = socket.socket(family, stype, proto)
        try:
            with cancel.register(real):
                real.settimeout(timeout)
                real.setblocking(False)
                try:
                    real.connect(sockaddr)
                except BlockingIOError:
                    while True:
                        if cancel.is_cancelled():
                            raise OperationCancelled()
                        left = deadline - time.monotonic()
                        if left <= 0:
                            raise socket.timeout("connect timed out")
                        _r, writable, _x = select.select([], [real], [],
                                                         min(0.1, left))
                        if writable:
                            break
                real.setblocking(True)
                return CountingSocket(real, counter)
        except OperationCancelled:
            real.close()
            raise
        except OSError as exc:
            real.close()
            last_error = exc
            continue
    if last_error:
        raise last_error
    raise socket.timeout("connect timed out")
