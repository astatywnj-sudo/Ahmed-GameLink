"""DNS test — direct queries to SPECIFIC servers, with exact byte counting.

Why a minimal stdlib DNS client instead of dnspython: dnspython hides its
sockets, which would make exact DNS byte accounting (Spec §8.3 — the
project's top priority) impossible. The query here is built wire-format
by hand and sent through CountingUDPSocket, so `sent`/`received` are the
EXACT DNS wire bytes exchanged with the tested server.

Scope kept deliberately narrow for reliability: A records over UDP with
EDNS disabled; truncation is reported as an error (never guessed).
The system's configured DNS servers are read via GetNetworkParams —
no admin rights, no drivers (Spec §6).
"""

import ctypes
import ctypes.wintypes as wt
import random
import socket
import struct
import time

from core.counting_socket import CountingUDPSocket
from core.data_counter import DataCounter

DNS_PORT = 53
TYPE_A = 1
CLASS_IN = 1


class DnsResult:
    __slots__ = ("ok", "server", "domain", "addresses", "rtt_ms",
                 "sent_bytes", "received_bytes", "error")

    def __init__(self, *, ok: bool, server: str, domain: str,
                 addresses: list[str] | None = None, rtt_ms: float = 0.0,
                 sent_bytes: int = 0, received_bytes: int = 0, error: str = "") -> None:
        self.ok = ok
        self.server = server
        self.domain = domain
        self.addresses = addresses or []
        self.rtt_ms = rtt_ms
        self.sent_bytes = sent_bytes
        self.received_bytes = received_bytes
        self.error = error


# ------------------------------------------------------------ wire format
def build_a_query(domain: str, qid: int | None = None) -> tuple[bytes, int]:
    """Return (wire_bytes, query_id). Standard 12-byte header, RD=1."""
    qid = qid if qid is not None else random.randrange(0x10000)
    header = struct.pack(">HHHHHH", qid, 0x0100, 1, 0, 0, 0)
    qname = b"".join(bytes([len(label)]) + label.encode("idna")
                     for label in domain.split(".")) + b"\x00"
    wire = header + qname + struct.pack(">HH", TYPE_A, CLASS_IN)
    return wire, qid


def _read_name(data: bytes, offset: int) -> tuple[str, int]:
    """Parse a (possibly compressed) domain name; return (name, next_offset)."""
    labels: list[str] = []
    jumped = False
    next_offset = offset + 1
    while True:
        if offset >= len(data):
            raise ValueError("truncated name")
        length = data[offset]
        if length & 0xC0 == 0xC0:                       # compression pointer
            if offset + 1 >= len(data):
                raise ValueError("truncated pointer")
            pointer = ((length & 0x3F) << 8) | data[offset + 1]
            if not jumped:
                next_offset = offset + 2
                jumped = True
            offset = pointer
            continue
        if length == 0:
            if not jumped:
                next_offset = offset + 1
            break
        offset += 1
        if offset + length > len(data):
            raise ValueError("truncated label")
        labels.append(data[offset:offset + length].decode("ascii", "replace"))
        offset += length
    return ".".join(labels), next_offset


def parse_a_reply(data: bytes, qid: int) -> tuple[int, list[str]]:
    """Return (rcode, [ipv4 addresses]). Raises ValueError on malformed data."""
    if len(data) < 12:
        raise ValueError("reply too short")
    reply_qid, flags, qdcount, ancount, _, _ = struct.unpack(">HHHHHH", data[:12])
    if reply_qid != qid:
        raise ValueError("query id mismatch")
    rcode = flags & 0x000F
    offset = 12
    for _ in range(qdcount):
        _, offset = _read_name(data, offset)
        offset += 4                                     # QTYPE + QCLASS
    addresses: list[str] = []
    for _ in range(ancount):
        _, offset = _read_name(data, offset)            # answer owner name
        if offset + 10 > len(data):
            raise ValueError("truncated answer header")
        rtype, _rclass, _ttl, rdlength = struct.unpack(">HHIH", data[offset:offset + 10])
        offset += 10
        if offset + rdlength > len(data):
            raise ValueError("truncated rdata")
        if rtype == TYPE_A and rdlength == 4:
            addresses.append(socket.inet_ntoa(data[offset:offset + 4]))
        offset += rdlength
    return rcode, addresses


# ------------------------------------------------- system DNS servers (Win)
class _IP_ADDR_STRING(ctypes.Structure):
    _fields_ = [("Next", ctypes.c_void_p),
                ("IpAddress", ctypes.c_char * 16),
                ("IpMask", ctypes.c_char * 16),
                ("Context", wt.DWORD)]


class _FIXED_INFO(ctypes.Structure):
    _fields_ = [("HostName", ctypes.c_char * 132),
                ("DomainName", ctypes.c_char * 132),
                ("CurrentDnsServer", ctypes.c_void_p),
                ("DnsServerList", _IP_ADDR_STRING)]


def get_system_dns_servers() -> list[str]:
    """IPv4 DNS servers configured by Windows (via iphlpapi, no admin)."""
    iphlpapi = ctypes.WinDLL("iphlpapi")
    iphlpapi.GetNetworkParams.argtypes = [ctypes.POINTER(_FIXED_INFO),
                                          ctypes.POINTER(ctypes.c_ulong)]
    iphlpapi.GetNetworkParams.restype = wt.DWORD

    size = ctypes.c_ulong(ctypes.sizeof(_FIXED_INFO) + 4096)
    buffer = ctypes.create_string_buffer(size.value)
    info = ctypes.cast(buffer, ctypes.POINTER(_FIXED_INFO))

    if iphlpapi.GetNetworkParams(info, ctypes.byref(size)) != 0:
        # ERROR_BUFFER_OVERFLOW → caller-supplied buffer was too small
        if size.value > 0x10000:
            return []
        buffer = ctypes.create_string_buffer(size.value)
        info = ctypes.cast(buffer, ctypes.POINTER(_FIXED_INFO))
        if iphlpapi.GetNetworkParams(info, ctypes.byref(size)) != 0:
            return []

    servers: list[str] = []
    node = ctypes.cast(ctypes.byref(info.contents.DnsServerList),
                       ctypes.POINTER(_IP_ADDR_STRING))
    while node:
        raw = node.contents.IpAddress                  # c_char*16 → bytes
        ip = raw.split(b"\x00", 1)[0].decode("ascii", "replace") if raw else ""
        if ip and ":" not in ip and ip not in servers:   # IPv4 only, deduped
            servers.append(ip)
        node = ctypes.cast(node.contents.Next, ctypes.POINTER(_IP_ADDR_STRING))
    return servers


# --------------------------------------------------------------- the check
def query_a(server: str, domain: str, *, timeout: float = 10.0,
            counter: DataCounter, cancel=None) -> DnsResult:
    """One A-record query to a specific DNS server, bytes counted exactly."""
    try:
        wire, qid = build_a_query(domain)
    except (UnicodeError, struct.error):
        return DnsResult(ok=False, server=server, domain=domain, error="bad_query")

    start = time.perf_counter()
    udp = CountingUDPSocket(socket.AF_INET, socket.SOCK_DGRAM, counter)
    try:
        udp.settimeout(timeout)
        if cancel is not None:
            # Cancel closes the UDP socket → blocked recvfrom raises now.
            with cancel.register(udp):
                udp.sendto(wire, (server, DNS_PORT))
                reply, _addr = udp.recvfrom(4096)
        else:
            udp.sendto(wire, (server, DNS_PORT))
            reply, _addr = udp.recvfrom(4096)
        rtt_ms = (time.perf_counter() - start) * 1000.0
        try:
            rcode, addresses = parse_a_reply(reply, qid)
        except ValueError as exc:
            return DnsResult(ok=False, server=server, domain=domain,
                             sent_bytes=len(wire), received_bytes=len(reply),
                             error=f"bad_reply:{exc}")
        if rcode != 0:
            reason = {1: "format_error", 2: "server_failure",
                      3: "nxdomain", 4: "not_implemented",
                      5: "refused"}.get(rcode, f"rcode_{rcode}")
            return DnsResult(ok=False, server=server, domain=domain,
                             sent_bytes=len(wire), received_bytes=len(reply),
                             error=reason)
        return DnsResult(ok=True, server=server, domain=domain, addresses=addresses,
                         rtt_ms=rtt_ms, sent_bytes=len(wire), received_bytes=len(reply))
    except socket.timeout:
        return DnsResult(ok=False, server=server, domain=domain,
                         sent_bytes=len(wire), error="timeout")
    except OSError as exc:
        reason = "cancelled" if (cancel is not None and cancel.is_cancelled()) \
            else type(exc).__name__.lower()
        return DnsResult(ok=False, server=server, domain=domain,
                         error=reason)
    finally:
        udp.close()
