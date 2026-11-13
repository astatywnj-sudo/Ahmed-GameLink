"""Diagnostics orchestrator (Spec §5): sequential checks, hard deadlines.

Guarantees:
- Sequential (never parallel) to keep diagnosis accurate and cheap.
- Per-check cap: min(CHECK_TIMEOUT_SECONDS, remaining budget).
- Total budget: TOTAL_BUDGET_SECONDS (45 s) — enforced via a monotonic
  deadline; a step that can't start in time is SKIPPED with reason
  'time_budget_exceeded' (never runs past the budget).
- Cancel: cooperative (between steps) + aggressive (closes the blocked
  socket, see core/cancel.py) — the 'cancelled' state propagates.
- Data counter (§8.3): reset_check() at start; snapshot taken at the end.
"""

import time

from core import config
from core.cancel import CANCELLED, CancelContext, OperationCancelled
from core.data_counter import DataCounter, SESSION_COUNTER
from core.internet_check import check_internet
from core.dns_test import get_system_dns_servers, query_a
from core.tcp_test import tcp_connect
from core.http_client import http_request

DNS_TEST_DOMAIN = "web.roblox.com"

# Steps of the smart check, in order. HTTPS endpoints chosen for signal:
# web (main site), apis (public API), client_api (bootstrap config that
# the game client itself fetches).
HTTPS_ENDPOINT_KEYS = ("web", "apis", "client_api")


class StepResult:
    __slots__ = ("id", "ok", "error", "elapsed_ms", "detail")

    def __init__(self, step_id: str, *, ok: bool, error: str = "",
                 elapsed_ms: float = 0.0, detail: dict | None = None) -> None:
        self.id = step_id
        self.ok = ok
        self.error = error
        self.elapsed_ms = elapsed_ms
        self.detail = detail or {}

    def as_dict(self) -> dict:
        return {"id": self.id, "ok": self.ok, "error": self.error,
                "elapsed_ms": round(self.elapsed_ms, 1), "detail": self.detail}


class DiagnosticResult:
    __slots__ = ("steps", "cancelled", "elapsed_s", "data", "internet_ok")

    def __init__(self) -> None:
        self.steps: list[StepResult] = []
        self.cancelled = False
        self.elapsed_s = 0.0
        self.data: dict = {}
        self.internet_ok = False

    def step(self, step_id: str) -> StepResult | None:
        for s in self.steps:
            if s.id == step_id:
                return s
        return None

    def as_dict(self) -> dict:
        return {
            "cancelled": self.cancelled,
            "elapsed_s": round(self.elapsed_s, 2),
            "internet_ok": self.internet_ok,
            "steps": [s.as_dict() for s in self.steps],
            "data_usage": self.data,
        }


def _remaining(deadline: float) -> float:
    return deadline - time.monotonic()


def _timeout_for(deadline: float, cap: float) -> float:
    """Per-check timeout = min(cap, remaining budget − safety margin).
    Below the margin the step cannot start — the orchestrator must stay
    strictly INSIDE the 45 s budget (observed overhead ≈ 0.2 s)."""
    left = _remaining(deadline)
    if left < 1.5:
        return 0.0
    return min(cap, left - 0.5)


def run_diagnostics(cancel: CancelContext, *,
                    counter: DataCounter = SESSION_COUNTER,
                    on_step=None, on_step_done=None,
                    on_progress=None) -> DiagnosticResult:
    """Run the full sequential check. `on_step(id)`, `on_step_done(StepResult)`
    and `on_progress(0..100)` are plain callables (Qt-free core)."""
    result = DiagnosticResult()
    counter.reset_check()                        # Spec §8.3 — every check start
    start = time.perf_counter()
    deadline = start + config.TOTAL_BUDGET_SECONDS
    total_steps = 1 + len(config.DNS_SERVERS) + 1 + len(HTTPS_ENDPOINT_KEYS) + 1

    def emit_progress() -> None:
        if on_progress:
            on_progress(min(100, int(len(result.steps) * 100 / total_steps)))

    def run_step(step_id: str, fn, cap: float) -> StepResult | None:
        """One sequential step, honouring cancel + budget. Returns None
        when cancelled."""
        if cancel.is_cancelled():
            return None
        timeout = _timeout_for(deadline, cap)
        if timeout <= 0:
            step = StepResult(step_id, ok=False, error="time_budget_exceeded")
            result.steps.append(step)
            if on_step_done:
                on_step_done(step)
            emit_progress()
            return step
        if on_step:
            on_step(step_id)
        try:
            step = fn(timeout)
        except OperationCancelled:
            step = StepResult(step_id, ok=False, error=CANCELLED)
        result.steps.append(step)
        if on_step_done:
            on_step_done(step)
        emit_progress()
        if step.error == CANCELLED:
            result.cancelled = True
            return None
        return step

    # ------------------------------------------------ 1) internet up?
    def do_internet(timeout: float) -> StepResult:
        r = check_internet(counter, timeout=timeout, cancel=cancel)
        return StepResult("internet", ok=r.ok, error=r.error,
                          elapsed_ms=r.elapsed_ms, detail={"status": r.status})

    step = run_step("internet", do_internet, config.CHECK_TIMEOUT_SECONDS)
    if step is None or result.cancelled:
        return _finish(result, counter, start)
    result.internet_ok = step.ok
    if not step.ok:
        # Spec §5: no internet at all → stop, no nonsense "solutions".
        return _finish(result, counter, start)

    # -------------------------------------------------------- 2) DNS
    resolved_ip = ""
    system_dns = get_system_dns_servers()
    for key, _desc in config.DNS_SERVERS:
        if cancel.is_cancelled():
            return _finish(result, counter, start)
        server = system_dns[0] if key == "system" else key
        if not server:
            step = StepResult(f"dns_{key}", ok=False, error="no_system_dns")
            result.steps.append(step)
            if on_step_done:
                on_step_done(step)
            emit_progress()
            continue

        def do_dns(timeout: float, _server=server, _key=key) -> StepResult:
            r = query_a(_server, DNS_TEST_DOMAIN, timeout=timeout,
                        counter=counter, cancel=cancel)
            detail = {"server": _server, "addresses": r.addresses,
                      "sent_bytes": r.sent_bytes, "received_bytes": r.received_bytes}
            return StepResult(f"dns_{_key}", ok=r.ok, error=r.error,
                              elapsed_ms=r.rtt_ms, detail=detail)

        step = run_step(f"dns_{key}", do_dns, 5.0)
        if step is None or result.cancelled:
            return _finish(result, counter, start)
        if step.ok and step.detail.get("addresses"):
            resolved_ip = resolved_ip or step.detail["addresses"][0]

    # ------------------------------------------------- 3) TCP to Roblox
    # Use the IP resolved by a working DNS when available (the system
    # resolver may be poisoned); numeric host → no getaddrinfo needed.
    tcp_host = resolved_ip or "web.roblox.com"

    def do_tcp(timeout: float) -> StepResult:
        r = tcp_connect(tcp_host, 443, timeout=timeout, counter=counter,
                        cancel=cancel)
        return StepResult("tcp_roblox", ok=r.ok, error=r.error,
                          elapsed_ms=r.rtt_ms, detail={"host": tcp_host})

    step = run_step("tcp_roblox", do_tcp, config.CHECK_TIMEOUT_SECONDS)
    if step is None or result.cancelled:
        return _finish(result, counter, start)

    # ----------------------------------------- 4) HTTPS to Roblox APIs
    https_ok = False
    for name in HTTPS_ENDPOINT_KEYS:
        if cancel.is_cancelled():
            return _finish(result, counter, start)
        url, _desc = config.ROBLOX_ENDPOINTS[name]

        def do_https(timeout: float, _url=url, _name=name) -> StepResult:
            r = http_request("GET", _url, counter=counter, timeout=timeout,
                             max_body=2048, cancel=cancel)
            return StepResult(f"https_{_name}", ok=r.ok and r.status < 500,
                              error=r.error or "",
                              detail={"status": r.status, "url": _url})

        step = run_step(f"https_{name}", do_https, 8.0)
        if step is None or result.cancelled:
            return _finish(result, counter, start)
        https_ok = https_ok or step.ok

    # ------------------- 5) mirror evaluation (a REAL solution check)
    if not https_ok and _remaining(deadline) >= 8.0 and not cancel.is_cancelled():
        url, _desc = config.ROBLOX_ENDPOINTS["proxy_web"]

        def do_proxy(timeout: float) -> StepResult:
            r = http_request("GET", url, counter=counter, timeout=timeout,
                             max_body=2048, cancel=cancel)
            return StepResult("https_proxy_web", ok=r.ok and r.status < 500,
                              error=r.error or "", detail={"status": r.status,
                                                           "url": url})

        run_step("https_proxy_web", do_proxy, 8.0)
        if result.cancelled:
            return _finish(result, counter, start)

    return _finish(result, counter, start)


def _finish(result: DiagnosticResult, counter: DataCounter, start: float) -> DiagnosticResult:
    result.elapsed_s = time.perf_counter() - start
    result.data = counter.snapshot()
    return result
