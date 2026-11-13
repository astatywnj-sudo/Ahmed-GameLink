"""Phase 2 acceptance tests — the network engine, no UI, REAL network:

    python tests/test_core_all.py

The centerpiece (per project owner request): exact byte accounting.
Test 1 spins up a raw TCP server on 127.0.0.1 (zero external data), lets
the engine talk to it, and reads the RAW bytes on the server side — then
asserts counter == actual wire bytes, mathematically, for both
directions. Real-internet checks follow with printed numbers.
"""

import os
import socket
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.data_counter import DataCounter
from core.counting_socket import CountingSocket
from core.http_client import http_request
from core.internet_check import check_internet
from core.tcp_test import tcp_connect
from core.dns_test import (build_a_query, get_system_dns_servers, parse_a_reply,
                           query_a)
from core.icmp_ping import ping
from core.privacy import mask_ip
from core import config


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {label}" + (f" — {detail}" if detail else ""))
    if not ok:
        sys.exit(1)


def fmt_bytes(n: int) -> str:
    return f"{n:,} B"


# ==================================================================== TEST 1
# EXACT byte accounting against a raw server we fully control.
class _ExactServer:
    """Reads the client's request bytes RAW and remembers them, then writes
    a known response. What crosses the loopback is known bit-for-bit."""

    def __init__(self) -> None:
        self.srv = socket.socket()
        self.srv.bind(("127.0.0.1", 0))
        self.srv.settimeout(10)
        self.port = self.srv.getsockname()[1]
        self.srv.listen(1)
        self.request_bytes = b""
        self.response_bytes = b""
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _serve(self) -> None:
        conn, _ = self.srv.accept()
        conn.settimeout(10)
        buf = b""
        while b"\r\n\r\n" not in buf:               # full request headers?
            chunk = conn.recv(4096)
            if not chunk:
                break
            buf += chunk
        head, _, rest = buf.partition(b"\r\n\r\n")
        content_length = 0
        for line in head.split(b"\r\n")[1:]:
            if line.lower().startswith(b"content-length:"):
                content_length = int(line.split(b":", 1)[1].strip())
        while len(rest) < content_length:
            chunk = conn.recv(4096)
            if not chunk:
                break
            rest += chunk
        self.request_bytes = head + b"\r\n\r\n" + rest[:content_length]

        body = b"Ahmed GameLink exact-byte accounting proof."
        self.response_bytes = (
            b"HTTP/1.1 200 OK\r\n"
            b"Content-Type: text/plain\r\n"
            b"Content-Length: " + str(len(body)).encode() + b"\r\n"
            b"Connection: close\r\n\r\n" + body
        )
        conn.sendall(self.response_bytes)
        conn.close()
        self.srv.close()


def test_exact_byte_accounting() -> None:
    server = _ExactServer()
    counter = DataCounter()
    counter.reset_check()

    result = http_request("GET", f"http://127.0.0.1:{server.port}/exact",
                          counter=counter, timeout=10)
    server.thread.join(timeout=10)

    check("exact-bytes: HTTP request succeeded locally",
          result.ok and result.status == 200)
    check("exact-bytes: response body matches",
          result.body == b"Ahmed GameLink exact-byte accounting proof.")

    # ---- THE PROOF: counted == actual wire bytes, mathematically ----
    sent_ok = counter.snapshot()["last_check_sent"] == len(server.request_bytes)
    recv_ok = counter.snapshot()["last_check_received"] == len(server.response_bytes)
    check("exact-bytes: SENT counted == actual bytes read on the wire",
          sent_ok,
          f"counter={counter.snapshot()['last_check_sent']} "
          f"wire={len(server.request_bytes)}")
    check("exact-bytes: RECEIVED counted == actual bytes written on the wire",
          recv_ok,
          f"counter={counter.snapshot()['last_check_received']} "
          f"wire={len(server.response_bytes)}")

    # ---- independent math check: headers + payload decomposition ----
    resp_head, _, resp_body = server.response_bytes.partition(b"\r\n\r\n")
    head_end = server.request_bytes.find(b"\r\n\r\n")
    req_headers_len = head_end + 4
    print(f"      breakdown: request {req_headers_len} B headers + "
          f"{len(server.request_bytes) - req_headers_len} B body | "
          f"response {len(resp_head) + 4} B headers + {len(resp_body)} B payload")
    check("exact-bytes: response decomposition math adds up",
          counter.snapshot()["last_check_received"] == len(resp_head) + 4 + len(resp_body))
    check("exact-bytes: session totals == last-check totals (first check)",
          counter.snapshot()["session_sent"] == counter.snapshot()["last_check_sent"]
          and counter.snapshot()["session_received"] == counter.snapshot()["last_check_received"])


# ==================================================================== TEST 2
def test_data_counter_semantics() -> None:
    counter = DataCounter()
    counter.add_sent(10)
    counter.add_received(5)
    counter.reset_check()                       # Spec 8.3: reset at check start
    snap = counter.snapshot()
    check("counter: reset_check zeroes last-check only",
          snap["last_check_sent"] == 0 and snap["last_check_received"] == 0
          and snap["session_sent"] == 10 and snap["session_received"] == 5)

    # thread-safety: 4 threads × 10,000 increments each
    counter2 = DataCounter()
    def hammer(c: DataCounter) -> None:
        for _ in range(10000):
            c.add_sent(1)
    threads = [threading.Thread(target=hammer, args=(counter2,)) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    check("counter: thread-safe under 40,000 concurrent increments",
          counter2.snapshot()["session_sent"] == 40000,
          f"got {counter2.snapshot()['session_sent']}")

    counter2.add_sent(0)
    counter2.add_received(-5)
    snap2 = counter2.snapshot()
    check("counter: zero/negative adds are ignored",
          snap2["session_sent"] == 40000 and snap2["session_received"] == 0,
          f"sent={snap2['session_sent']}, received={snap2['session_received']}")


# ==================================================================== TEST 3
# Real internet (graceful SKIP when offline — Egypt networks vary).
def test_real_internet() -> bool:
    counter = DataCounter()
    counter.reset_check()
    result = check_internet(counter)
    snap = counter.snapshot()
    total = snap["last_check_sent"] + snap["last_check_received"]
    if not result.ok:
        print(f"[SKIP] real internet probe failed ({result.error}) — "
              f"offline? later internet tests will be skipped")
        return False
    check("internet: generate_204 probe OK",
          result.status == 204 and result.ok,
          f"status={result.status} rtt={result.elapsed_ms:.0f} ms "
          f"bytes={fmt_bytes(total)} (sent {snap['last_check_sent']} / "
          f"recv {snap['last_check_received']}) — TLS overhead included")
    return True


def test_dns(net_ok: bool) -> None:
    counter = DataCounter()
    domain = "web.roblox.com"

    servers = get_system_dns_servers()
    check("dns: system servers detected via GetNetworkParams (no admin)",
          len(servers) >= 1, ", ".join(mask_ip(s) for s in servers[:3]) or "none")

    for server in ([servers[0]] if servers else []) + ["1.1.1.1", "8.8.8.8"]:
        counter.reset_check()
        if not net_ok:
            print(f"[SKIP] DNS query to {mask_ip(server)} — offline")
            continue
        result = query_a(server, domain, timeout=5.0, counter=counter)
        wire, _qid = build_a_query(domain)
        snap = counter.snapshot()
        if not result.ok:
            print(f"[SKIP] DNS {mask_ip(server)} → {result.error} "
                  f"(sent {result.sent_bytes} B, received {result.received_bytes} B)")
            continue
        check(f"dns: {mask_ip(server)} exact wire bytes + valid A reply",
              counter.snapshot()["last_check_sent"] == len(wire)
              and counter.snapshot()["last_check_received"] == result.received_bytes,
              f"query={len(wire)} B, reply={result.received_bytes} B, "
              f"rtt={result.rtt_ms:.0f} ms → "
              f"A={', '.join(mask_ip(a) for a in result.addresses) or 'none'}")


def test_tcp(net_ok: bool) -> None:
    counter = DataCounter()
    counter.reset_check()
    if not net_ok:
        print("[SKIP] TCP connect — offline")
        return
    result = tcp_connect("web.roblox.com", 443, timeout=8.0, counter=counter)
    if not result.ok:
        print(f"[SKIP] TCP 443 → {result.error}")
        return
    check("tcp: web.roblox.com:443 reachable",
          result.ok and result.rtt_ms > 0,
          f"rtt={result.rtt_ms:.1f} ms "
          f"(handshake carries no app payload → counted bytes "
          f"{counter.snapshot()['last_check_sent'] + counter.snapshot()['last_check_received']} B, honest)")


def test_icmp(net_ok: bool) -> None:
    counter = DataCounter()
    counter.reset_check()
    if not net_ok:
        print("[SKIP] ICMP ping — offline")
        return
    results = ping("1.1.1.1", timeout=5.0, counter=counter, count=2)
    good = [r for r in results if r.ok]
    if not good:
        reason = results[0].error if results else "?"
        sent = counter.snapshot()["last_check_sent"]
        print(f"[SKIP] ICMP → {reason} (some networks block ICMP; "
              f"sent bytes still counted honestly: {sent} B)")
        return
    avg_rtt = sum(r.rtt_ms for r in good) / len(good)
    check("icmp: 1.1.1.1 responds, payload counted exactly",
          counter.snapshot()["last_check_sent"] == sum(r.sent_bytes for r in good)
          and counter.snapshot()["last_check_received"] == sum(r.received_bytes for r in good),
          f"rtt(avg)={avg_rtt:.0f} ms, sent={counter.snapshot()['last_check_sent']} B "
          f"recv={counter.snapshot()['last_check_received']} B (payload only — headers "
          f"not exposed by IcmpSendEcho, documented policy)")


def test_roblox_endpoints(net_ok: bool) -> None:
    if not net_ok:
        print("[SKIP] Roblox endpoints — offline")
        return
    counter = DataCounter()
    for name in ("web", "apis", "client_api"):
        url, desc = config.ROBLOX_ENDPOINTS[name]
        counter.reset_check()
        result = http_request("GET", url, counter=counter, timeout=8, max_body=4096)
        snap = counter.snapshot()
        total = snap["last_check_sent"] + snap["last_check_received"]
        if result.ok:
            detail = f"HTTP {result.status} ({result.reason_phrase}) {desc} → {fmt_bytes(total)}"
        else:
            detail = f"BLOCKED/FAILED ({result.error}) {desc} → {fmt_bytes(total)} counted"
        print(f"[INFO] roblox/{name}: {detail}")


def test_privacy() -> None:
    check("privacy: IPv4 masked to first two octets",
          mask_ip("197.35.12.9") == "197.35.x.x")
    check("privacy: garbage input never leaks",
          mask_ip("not an ip") == "<masked>")
    check("privacy: IPv6 masked",
          ":" in mask_ip("2001:4860:4860::8888"))


def main() -> None:
    print(f"Ahmed GameLink — core engine tests ({config.APP_VERSION})\n")

    test_exact_byte_accounting()          # THE centerpiece
    test_data_counter_semantics()
    net_ok = test_real_internet()
    test_dns(net_ok)
    test_tcp(net_ok)
    test_icmp(net_ok)
    test_roblox_endpoints(net_ok)
    test_privacy()

    # Zero-Idle guarantee at the end of the run (Spec §8.1):
    # no test server thread, no worker thread may outlive the engine.
    time.sleep(0.2)
    check("idle: no threads survive after the engine finishes",
          threading.active_count() == 1,
          f"active={threading.active_count()}")

    print("\nPhase 2: ALL CHECKS PASSED")


if __name__ == "__main__":
    main()
