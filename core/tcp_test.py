"""TCP reachability + round-trip-time check.

Connect-time RTT approximates the SYN→SYN-ACK round trip, the same
quantity ping.exe shows for TCP handshake. Bytes through the socket
after connect are counted (usually 0 for a pure connect/close probe —
that's honest: a TCP handshake carries no application payload).
"""

import socket
import time

from core.cancel import OperationCancelled
from core.counting_socket import counting_connect
from core.data_counter import DataCounter


class TcpResult:
    __slots__ = ("ok", "host", "port", "rtt_ms", "error")

    def __init__(self, *, ok: bool, host: str, port: int,
                 rtt_ms: float = 0.0, error: str = "") -> None:
        self.ok = ok
        self.host = host
        self.port = port
        self.rtt_ms = rtt_ms
        self.error = error


def tcp_connect(host: str, port: int, *, timeout: float = 10.0,
                counter: DataCounter, cancel=None) -> TcpResult:
    start = time.perf_counter()
    try:
        sock = counting_connect((host, port), timeout=timeout, counter=counter,
                                cancel=cancel)
        rtt_ms = (time.perf_counter() - start) * 1000.0
        sock.close()
        return TcpResult(ok=True, host=host, port=port, rtt_ms=rtt_ms)
    except OperationCancelled:
        return TcpResult(ok=False, host=host, port=port, error="cancelled")
    except socket.gaierror:
        return TcpResult(ok=False, host=host, port=port, error="dns_resolution_failed")
    except (socket.timeout, TimeoutError):
        return TcpResult(ok=False, host=host, port=port, error="timeout")
    except ConnectionRefusedError:
        return TcpResult(ok=False, host=host, port=port, error="refused")
    except OSError as exc:
        return TcpResult(ok=False, host=host, port=port,
                         error=type(exc).__name__.lower())
