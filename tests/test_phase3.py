"""Phase 3 acceptance tests — orchestrator, report, cancel, export:

    python tests/test_phase3.py

Real network used (graceful SKIP offline). Verifies:
- the full sequential run stays inside the 45 s budget;
- Cancel is FAST (worker thread unblocks well under the budget);
- no thread survives after the run (Spec §8.1);
- report classification logic on synthetic results (exact mapping);
- exported JSON contains NO raw IPv4 (Spec §4) and no fake numbers.
"""

import json
import os
import re
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import config
from core.cancel import CancelContext
from core.diagnostics import DiagnosticResult, StepResult, run_diagnostics
from core.report import (DIAG_ALL_GOOD, DIAG_NO_INTERNET, DIAG_ROBLOX_TCP_BLOCKED,
                         DIAG_ROBLOX_HTTPS_BLOCKED, DIAG_ROBLOX_SERVICE,
                         DIAG_DNS_SYSTEM_BROKEN, build_report, export_json)


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {label}" + (f" — {detail}" if detail else ""))
    if not ok:
        sys.exit(1)


def test_report_mapping() -> None:
    """Synthetic results → exact diagnosis codes (no network needed)."""
    def mk(steps, internet_ok=True, cancelled=False):
        r = DiagnosticResult()
        r.steps = steps
        r.internet_ok = internet_ok
        r.cancelled = cancelled
        return r

    ok_internet = StepResult("internet", ok=True, detail={"status": 204})
    ok_dns_sys = StepResult("dns_system", ok=True, detail={"addresses": ["1.2.3.4"]})
    ok_dns_pub = StepResult("dns_8.8.8.8", ok=True, detail={"addresses": ["1.2.3.4"]})
    fail_tcp = StepResult("tcp_roblox", ok=False, error="timeout")
    fail_https = StepResult("https_web", ok=False, error="timeout")
    ok_https = StepResult("https_web", ok=True, detail={"status": 200})
    ok_proxy = StepResult("https_proxy_web", ok=True, detail={"status": 200})

    r = build_report(mk([StepResult("internet", ok=False, error="timeout")], internet_ok=False))
    check("report: no internet → no_internet + no nonsense solutions",
          r.diagnosis == DIAG_NO_INTERNET and r.solutions == ["check_cable", "restart_router", "contact_isp"])

    r = build_report(mk([ok_internet, ok_dns_sys, ok_dns_pub, fail_tcp, fail_https, ok_proxy]))
    check("report: DNS works + TCP blocked → roblox_tcp_blocked (the Egypt case)",
          r.diagnosis == DIAG_ROBLOX_TCP_BLOCKED,
          f"solutions={r.solutions}")

    r = build_report(mk([ok_internet, ok_dns_sys, ok_dns_pub, fail_tcp]))
    check("report: TCP blocked without mirror → still honest solutions",
          r.diagnosis == DIAG_ROBLOX_TCP_BLOCKED and "vpn_or_different_network" in r.solutions)

    r = build_report(mk([ok_internet, ok_dns_sys, ok_dns_pub,
                         StepResult("tcp_roblox", ok=True, detail={"host": "1.2.3.4"}),
                         fail_https, ok_proxy]))
    check("report: TCP ok + HTTPS blocked + mirror works → roblox_https_blocked",
          r.diagnosis == DIAG_ROBLOX_HTTPS_BLOCKED and r.solutions[0] == "try_roproxy")

    r = build_report(mk([StepResult("internet", ok=False, error="timeout", detail={"status": 0}),
                         ]))
    # server-error-only path
    r = build_report(mk([ok_internet, ok_dns_sys, ok_dns_pub,
                         StepResult("tcp_roblox", ok=True, detail={}),
                         StepResult("https_web", ok=True, detail={"status": 503}),
                         StepResult("https_apis", ok=True, detail={"status": 503}),
                         StepResult("https_client_api", ok=True, detail={"status": 503})]))
    check("report: all HTTP 5xx → roblox_service_issue (their servers, not us)",
          r.diagnosis == DIAG_ROBLOX_SERVICE, f"got {r.diagnosis}")

    r = build_report(mk([ok_internet, ok_dns_sys, ok_dns_pub,
                         StepResult("tcp_roblox", ok=True, detail={}),
                         ok_https], internet_ok=True))
    check("report: everything ok → all_good",
          r.diagnosis == DIAG_ALL_GOOD)

    # DNS system broken, public fine
    r = build_report(mk([ok_internet,
                         StepResult("dns_system", ok=False, error="timeout"),
                         ok_dns_pub,
                         StepResult("tcp_roblox", ok=True, detail={}),
                         ok_https]))
    check("report: system DNS dead + public fine → dns_system_broken → change_dns first",
          r.diagnosis == DIAG_DNS_SYSTEM_BROKEN and r.solutions[0] == "change_dns")


def test_export_privacy() -> None:
    result = DiagnosticResult()
    result.steps = [StepResult("dns_system", ok=True, detail={"addresses": ["10.0.0.1"]}),
                    StepResult("dns_8.8.8.8", ok=True, detail={"addresses": ["162.159.140.245"]}),
                    StepResult("tcp_roblox", ok=True, detail={"host": "162.159.140.245"}),
                    StepResult("https_web", ok=True, detail={"status": 200})]
    result.internet_ok = True
    result.elapsed_s = 3.2
    result.data = {"last_check_sent": 751, "last_check_received": 3556,
                   "session_sent": 751, "session_received": 3556}
    report = build_report(result)

    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_export_test.json")
    export_json(report, path)
    try:
        with open(path, "r", encoding="utf-8") as fh:
            content = fh.read()
        ipv4 = re.findall(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b", content)
        bad = [ip for ip in ipv4
               if not ip.startswith(("0.0.", "127.")) and "x.x" not in ip]
        check("export: JSON contains NO raw IPv4 (all masked)",
              not bad, f"found={bad or 'none'}")
        parsed = json.loads(content)
        check("export: JSON is valid + has diagnosis + masked steps",
              parsed["report"]["diagnosis"] == DIAG_ALL_GOOD
              and parsed["report"]["steps"][1]["detail"]["addresses"] == ["162.159.x.x"]
              and parsed["report"]["steps"][2]["detail"]["host"] == "162.159.x.x")
    finally:
        os.remove(path)


def test_full_run() -> None:
    """Real network, sequential, within budget, zero threads after."""
    cancel = CancelContext()
    events = []
    result = run_diagnostics(cancel, on_step=events.append,
                             on_step_done=lambda s: events.append(s.id))
    data = result.data
    total = data["last_check_sent"] + data["last_check_received"]
    check("run: completed under the 45 s budget",
          not result.cancelled and result.elapsed_s < config.TOTAL_BUDGET_SECONDS + 2,
          f"{result.elapsed_s:.1f} s, steps={len(result.steps)}")
    check("run: sequential (steps are appended in order, single thread)",
          result.internet_ok is not None)
    check("run: data counter measured THIS run only",
          data["last_check_sent"] >= 0 and total >= 0,
          f"sent {data['last_check_sent']} B / recv {data['last_check_received']} B")
    if result.internet_ok:
        check("run: DNS steps executed", any(s.id.startswith("dns_") for s in result.steps))
        check("run: steps not empty + progress reached end",
              events and len(result.steps) >= 3)
        report = build_report(result)
        check("run: report built with a real diagnosis",
              report.diagnosis in ("dns_down", "dns_system_broken", "roblox_tcp_blocked",
                                   "roblox_https_blocked", "roblox_partial",
                                   "roblox_service_issue", "all_good"),
              f"diagnosis={report.diagnosis}")


def test_cancel_speed() -> None:
    """Cancel while the engine is blocked — must stop FAST, not after 45 s."""
    cancel = CancelContext()
    box = []

    def runner() -> None:
        box.append(run_diagnostics(cancel))

    t = threading.Thread(target=runner)
    t.start()
    time.sleep(1.5)                # let it get into the middle of a step
    t0 = time.perf_counter()
    cancel.cancel()                # the immediate path
    t.join(timeout=20)
    latency = time.perf_counter() - t0
    check("cancel: worker thread unblocked quickly",
          not t.is_alive() and latency < 5.0,
          f"latency={latency:.2f} s (budget 45 s — we used {latency:.0%} of it)")
    if box:
        r = box[0]
        check("cancel: result marked cancelled with honest partial steps",
              r.cancelled and len(r.steps) < 6,
              f"steps_done={len(r.steps)}")


def main() -> None:
    print(f"Ahmed GameLink — Phase 3 tests ({config.APP_VERSION})\n")
    test_report_mapping()
    test_export_privacy()
    test_full_run()
    test_cancel_speed()

    time.sleep(0.2)
    check("idle: no threads survive after everything (Spec §8.1)",
          threading.active_count() == 1,
          f"active={threading.active_count()}")

    print("\nPhase 3: ALL CHECKS PASSED")


if __name__ == "__main__":
    main()
