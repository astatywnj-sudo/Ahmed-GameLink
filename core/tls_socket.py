"""TLS with exact byte accounting.

Critical design note: ssl.wrap_socket() DETACHES the underlying socket
(ssl.py calls sock.detach()) and then talks to the raw file descriptor
directly — bytes would bypass any counting wrapper. Unacceptable for
Spec §8.3 (exact data accounting is the project's top priority).

Solution: ssl.MemoryBIO + SSLObject (wrap_bio). The TLS state machine
only holds bytes we explicitly give it, and every encrypted byte it
produces is flushed through CountingSocket.sendall(). The handshake,
renegotiation, records and close_notify — everything crosses our
counting wrapper. Nothing is estimated.
"""

import io
import ssl
import socket

from core.counting_socket import counting_connect
from core.data_counter import DataCounter


class TlsSocket:
    """A socket-like TLS connection for http.client, counting every wire
    byte exactly (encrypted bytes = real consumption)."""

    def __init__(self, address: tuple, host: str, timeout: float,
                 counter: DataCounter, context: ssl.SSLContext,
                 cancel=None) -> None:
        self._counter = counter
        self._raw = counting_connect(address, timeout=timeout, counter=counter,
                                     cancel=cancel)
        self._raw.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self._incoming = ssl.MemoryBIO()
        self._outgoing = ssl.MemoryBIO()
        self._ssl = context.wrap_bio(self._incoming, self._outgoing,
                                     server_hostname=host)
        if cancel is not None:
            # Register the raw socket for the whole handshake: cancel()
            # closes it and the blocked recv() unblocks immediately.
            with cancel.register(self._raw):
                self._handshake()
        else:
            self._handshake()

    # ------------------------------------------------------------- TLS I/O
    def _handshake(self) -> None:
        while True:
            try:
                self._ssl.do_handshake()
                break
            except ssl.SSLWantReadError:
                self._flush_outgoing()
                data = self._raw.recv(65536)
                if not data:
                    raise ConnectionResetError("connection closed during TLS handshake")
                self._incoming.write(data)
            except ssl.SSLWantWriteError:
                self._flush_outgoing()
        self._flush_outgoing()

    def _flush_outgoing(self) -> None:
        while self._outgoing.pending:
            self._raw.sendall(self._outgoing.read())

    def send(self, data, flags: int = 0) -> int:
        self._ssl.write(bytes(data))
        self._flush_outgoing()
        return len(data)

    def sendall(self, data, flags: int = 0) -> None:
        self._ssl.write(bytes(data))
        self._flush_outgoing()

    def recv(self, bufsize: int, flags: int = 0) -> bytes:
        while True:
            try:
                return self._ssl.read(bufsize)
            except ssl.SSLZeroReturnError:
                return b""                                     # clean EOF
            except ssl.SSLWantReadError:
                self._flush_outgoing()
                data = self._raw.recv(65536)
                if not data:
                    raise ConnectionResetError("connection closed by peer")
                self._incoming.write(data)

    # -------------------------------------- socket-like surface for client
    def makefile(self, mode: str, buffering: int = -1, **kwargs):
        if "r" not in mode:
            raise NotImplementedError("TlsSocket.makefile supports read modes only")
        return io.BufferedReader(_TlsRawReader(self), buffer_size=8192)

    def settimeout(self, value) -> None:
        self._raw.settimeout(value)

    def gettimeout(self):
        return self._raw.gettimeout()

    def setblocking(self, flag: bool) -> None:
        self._raw.setblocking(flag)

    def setsockopt(self, level, optname, value) -> None:
        self._raw.setsockopt(level, optname, value)

    def getsockopt(self, level, optname):
        return self._raw.getsockopt(level, optname)

    def fileno(self) -> int:
        return self._raw.fileno()

    def close(self) -> None:
        self._raw.close()

    @property
    def family(self):
        return self._raw.family

    @property
    def type(self):
        return self._raw.type

    @property
    def proto(self):
        return self._raw.proto


class _TlsRawReader(io.RawIOBase):
    """Reads plaintext through TlsSocket (which counts encrypted wire
    bytes internally) so http.client's response reader stays exact."""

    def __init__(self, tls: TlsSocket) -> None:
        self._tls = tls
        self._closed = False

    def readable(self) -> bool:
        return True

    def readinto(self, b) -> int:
        if self._closed:
            return 0
        try:
            data = self._tls.recv(len(b))
        except (ConnectionResetError, ssl.SSLError, OSError):
            self._closed = True
            return 0
        if not data:
            self._closed = True
            return 0
        n = min(len(data), len(b))
        b[:n] = data[:n]
        return n

    def fileno(self) -> int:
        return self._tls.fileno()

    def close(self) -> None:
        self._closed = True
        io.RawIOBase.close(self)


def tls_connect(address: tuple, host: str, timeout: float,
                counter: DataCounter, context: ssl.SSLContext | None = None,
                cancel=None) -> TlsSocket:
    ctx = context or ssl.create_default_context()
    return TlsSocket(address, host, timeout, counter, ctx, cancel=cancel)
