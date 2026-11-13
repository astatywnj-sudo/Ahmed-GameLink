"""Detailed per-target latency diagnostics (Network Diagnostics page).

Sequential ICMP echo (count=3) to a small fixed target list: the system's
DNS server, three public resolvers, and the main Roblox host. Every byte
is counted (ICMP payload policy — see core/icmp_ping.py), the run has a
hard budget, and cancellation is honoured between attempts.

NOTE: this is a latency/loss measurement only — it does NOT test whether
Roblox is reachable (TCP/HTTPS do that in the smart check); it measures
HOW FAST the path responds once reachable.
"""

import time

from core.cancel import CancelContext
from core.data_counter import DataCounter, SESSION_COUNTER
from core.dns_test import get_system_dns_servers
from core.icmp_ping import ping

BUDGET_SECONDS = 40.0        # generous, worst case ~6 s per target
PING_COUNT = 3
PING_TIMEOUT_S = 2.0

# (id, host): fixed list — same targets every run for comparable numbers.
def build_targets() -> list[tuple[str, str]]:
    targets: list[tuple[str, str]] = []
    system_dns = get_system_dns_servers()
    if system_dns:
        targets.append(("dns_system", system_dns[0]))
    targets += [
        ("dns_cloudflare", "1.1.1.1"),
        ("dns_google", "8.8.8.8"),
        ("dns_quad9", "9.9.9.9"),
        ("roblox_web", "web.roblox.com"),
    ]
    return targets


class TargetResult:
    __slots__ = ("id", "host", "ip", "ok", "rtts", "lost", "sent", "received",
                 "error")

    def __init__(self, target_id: str, host: str, *, ip: str = "", ok: bool = False,
                 rtts: list | None = None, lost: int = 0, sent: int = 0,
                 received: int = 0, error: str = "") -> None:
        self.id = target_id
        self.host = host
        self.ip = ip
        self.ok = ok
        self.rtts = rtts or []
        self.lost = lost
        self.sent = sent
        self.received = received
        self.error = error


class NetDiagResult:
    __slots__ = ("targets", "cancelled", "elapsed_s", "data")

    def __init__(self) -> None:
        self.targets: list[TargetResult] = []
        self.cancelled = False
        self.elapsed_s = 0.0
        self.data: dict = {}


def run_network_diagnostics(cancel: CancelContext, *,
                            counter: DataCounter = SESSION_COUNTER,
                            on_target=None, on_target_done=None) -> NetDiagResult:
    """Sequential per-target ping. Callbacks: on_target(id, host),
    on_target_done(TargetResult) — plain callables (Qt-free core)."""
    result = NetDiagResult()
    counter.reset_check()                    # Spec §8.3 — start of every check
    start = time.perf_counter()
    deadline = start + BUDGET_SECONDS

    for target_id, host in build_targets():
        if cancel.is_cancelled():
            result.cancelled = True
            break
        left = deadline - time.monotonic()
        if left < PING_TIMEOUT_S + 0.5:
            result.targets.append(TargetResult(target_id, host,
                                               error="time_budget_exceeded"))
            if on_target_done:
                on_target_done(result.targets[-1])
            continue

        if on_target:
            on_target(target_id, host)
        attempts = ping(host, timeout=PING_TIMEOUT_S, counter=counter,
                        count=PING_COUNT, cancel=cancel)
        rtts = [r.rtt_ms for r in attempts if r.ok]
        lost = sum(1 for r in attempts if not r.ok)
        sent = sum(r.sent_bytes for r in attempts)
        received = sum(r.received_bytes for r in attempts)
        ip = attempts[0].ip if attempts else ""
        error = attempts[0].error if (attempts and not rtts) else ""
        result.targets.append(TargetResult(target_id, host, ip=ip,
                                           ok=bool(rtts), rtts=rtts,
                                           lost=lost, sent=sent,
                                           received=received, error=error))
        if on_target_done:
            on_target_done(result.targets[-1])
        if cancel.is_cancelled():
            result.cancelled = True        # stopped mid-run, even at the last target
            break

    result.elapsed_s = time.perf_counter() - start
    result.data = counter.snapshot()
    return result
