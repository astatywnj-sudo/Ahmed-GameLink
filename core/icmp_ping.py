"""ICMP ping via the Windows IcmpSendEcho API — no raw sockets, no admin.

Byte accounting policy (documented, honest): IcmpSendEcho exposes only the
echo payload, so `sent`/`received` count the payload bytes exactly; the
ICMP/IP frame headers (~28 B/packet) are not exposed by this API and are
therefore not counted — same transparency policy as TCP/UDP.
"""

import ctypes
import ctypes.wintypes as wt
import socket
import time

from core.data_counter import DataCounter

ICMP_ECHO_REPLY_SUCCESS = 0
IP_REQ_TIMED_OUT = 11010

_payload = b"AhmedGameLink-probe-32b"[:32]  # honest, fixed-size probe


class PingResult:
    __slots__ = ("ok", "host", "ip", "rtt_ms", "sent_bytes", "received_bytes",
                 "error")

    def __init__(self, *, ok: bool, host: str, ip: str = "", rtt_ms: float = 0.0,
                 sent_bytes: int = 0, received_bytes: int = 0, error: str = "") -> None:
        self.ok = ok
        self.host = host
        self.ip = ip
        self.rtt_ms = rtt_ms
        self.sent_bytes = sent_bytes
        self.received_bytes = received_bytes
        self.error = error


class _IP_OPTION_INFORMATION(ctypes.Structure):
    _fields_ = [("Ttl", ctypes.c_ubyte), ("Tos", ctypes.c_ubyte),
                ("Flags", ctypes.c_ubyte), ("OptionsSize", ctypes.c_ubyte),
                ("OptionsData", ctypes.c_void_p)]


class _ICMP_ECHO_REPLY(ctypes.Structure):
    _fields_ = [("Address", wt.ULONG), ("Status", wt.ULONG),
                ("RoundTripTime", wt.ULONG), ("DataSize", wt.USHORT),
                ("Reserved", wt.USHORT), ("Data", ctypes.c_void_p),
                ("Options", _IP_OPTION_INFORMATION)]


def _resolve_ipv4(host: str) -> str:
    infos = socket.getaddrinfo(host, None, socket.AF_INET, socket.SOCK_DGRAM)
    return infos[0][4][0]


def ping(host: str, *, timeout: float = 10.0, counter: DataCounter,
         count: int = 1, cancel=None) -> list[PingResult]:
    """Send `count` echo requests and return one result per attempt.

    With a CancelContext, the flag is checked between attempts; a single
    in-flight IcmpSendEcho still completes (bounded by its own timeout) —
    cancel latency ≈ one echo timeout, documented honestly."""
    try:
        ip = _resolve_ipv4(host)
    except socket.gaierror:
        return [PingResult(ok=False, host=host, error="dns_resolution_failed")]

    iphlpapi = ctypes.WinDLL("iphlpapi")
    iphlpapi.IcmpCreateFile.restype = wt.HANDLE
    iphlpapi.IcmpCloseHandle.argtypes = [wt.HANDLE]
    iphlpapi.IcmpSendEcho.argtypes = [
        wt.HANDLE, wt.ULONG, ctypes.c_char_p, wt.WORD,
        ctypes.POINTER(_IP_OPTION_INFORMATION), ctypes.c_void_p, wt.DWORD, wt.DWORD,
    ]
    iphlpapi.IcmpSendEcho.restype = wt.DWORD

    handle = iphlpapi.IcmpCreateFile()
    if handle == -1 or handle is None:
        return [PingResult(ok=False, host=host, ip=ip, error="icmp_open_failed")]

    reply_buffer = (ctypes.c_char * (ctypes.sizeof(_ICMP_ECHO_REPLY) + len(_payload) + 8))()
    timeout_ms = int(timeout * 1000)
    results: list[PingResult] = []

    try:
        for _ in range(count):
            if cancel is not None and cancel.is_cancelled():
                break
            sent_bytes = len(_payload)
            dest_addr = int.from_bytes(socket.inet_aton(ip), "little")  # IPAddr = ULONG in network order
            replies = iphlpapi.IcmpSendEcho(
                handle, dest_addr, _payload, len(_payload), None,
                reply_buffer, len(reply_buffer), timeout_ms,
            )
            if replies >= 1:
                reply = ctypes.cast(reply_buffer, ctypes.POINTER(_ICMP_ECHO_REPLY)).contents
                counter.add_sent(sent_bytes)
                received = ctypes.string_at(reply.Data, reply.DataSize) \
                    if reply.Data and reply.DataSize else b""
                counter.add_received(len(received))
                status = reply.Status
                if status == ICMP_ECHO_REPLY_SUCCESS:
                    results.append(PingResult(ok=True, host=host, ip=ip,
                                              rtt_ms=float(reply.RoundTripTime),
                                              sent_bytes=sent_bytes,
                                              received_bytes=len(received)))
                elif status == IP_REQ_TIMED_OUT:
                    # The request DID cross the wire — count it honestly.
                    results.append(PingResult(ok=False, host=host, ip=ip,
                                              sent_bytes=sent_bytes, error="timeout"))
                else:
                    results.append(PingResult(ok=False, host=host, ip=ip,
                                              sent_bytes=sent_bytes,
                                              error=f"icmp_status_{status}"))
            else:
                results.append(PingResult(ok=False, host=host, ip=ip,
                                          error="icmp_send_failed"))
    finally:
        iphlpapi.IcmpCloseHandle(handle)

    return results
