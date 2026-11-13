"""Report builder (Spec §5): problem classification + honest solutions.

The UI renders diagnosis/solution codes through i18n so the user sees a
clear Arabic explanation (e.g. "DNS يعمل، لكن الاتصال بخوادم Roblox
محجوب"). The engine NEVER claims a solution "breaks blocking
automatically" — solutions are practical options with their requirements.

Export: JSON with ALL IPs masked (Spec §4) — safe to share.
"""

import json
import time

from core import config
from core.privacy import mask_ip

# ------------------------------------------------------------------ codes
# Diagnosis codes (machine → i18n: report.diag.<code>):
DIAG_NO_INTERNET = "no_internet"
DIAG_DNS_DOWN = "dns_down"
DIAG_DNS_SYSTEM_BROKEN = "dns_system_broken"
DIAG_ROBLOX_TCP_BLOCKED = "roblox_tcp_blocked"
DIAG_ROBLOX_HTTPS_BLOCKED = "roblox_https_blocked"
DIAG_ROBLOX_PARTIAL = "roblox_partial"
DIAG_ROBLOX_SERVICE = "roblox_service_issue"
DIAG_ALL_GOOD = "all_good"
DIAG_CANCELLED = "cancelled"

# Solution codes (machine → i18n: report.solution.<code>):
SOL_CHECK_CABLE = "check_cable"
SOL_RESTART_ROUTER = "restart_router"
SOL_CONTACT_ISP = "contact_isp"
SOL_CHANGE_DNS = "change_dns"
SOL_VPN_OR_NETWORK = "vpn_or_different_network"
SOL_TRY_ROPROXY = "try_roproxy"
SOL_CHECK_FIREWALL = "check_firewall"
SOL_WAIT_RETRY = "wait_retry"
SOL_NONE = "none"


class Report:
    __slots__ = ("diagnosis", "solutions", "internet_ok", "dns_public_ok",
                 "dns_system_ok", "tcp_ok", "https_ok", "proxy_ok",
                 "elapsed_s", "data", "steps")

    def __init__(self) -> None:
        self.diagnosis = DIAG_ALL_GOOD
        self.solutions: list[str] = []
        self.internet_ok = False
        self.dns_public_ok = False
        self.dns_system_ok = False
        self.tcp_ok = False
        self.https_ok = False
        self.proxy_ok = False
        self.elapsed_s = 0.0
        self.data: dict = {}
        self.steps: list = []

    def as_dict(self) -> dict:
        return {
            "diagnosis": self.diagnosis,
            "solutions": self.solutions,
            "internet_ok": self.internet_ok,
            "dns_public_ok": self.dns_public_ok,
            "dns_system_ok": self.dns_system_ok,
            "tcp_ok": self.tcp_ok,
            "https_ok": self.https_ok,
            "proxy_ok": self.proxy_ok,
            "elapsed_s": round(self.elapsed_s, 2),
            "data_usage": self.data,
            "steps": self.steps,
        }


def build_report(result) -> Report:
    """Classify a DiagnosticResult into a Report with honest solutions."""
    r = Report()
    r.elapsed_s = result.elapsed_s
    r.data = result.data
    r.steps = [s.as_dict() for s in result.steps]

    if result.cancelled:
        r.diagnosis = DIAG_CANCELLED
        r.solutions = [SOL_NONE]
        return r

    r.internet_ok = result.internet_ok

    def _step_ok(prefix: str) -> bool:
        return any(s.ok for s in result.steps if s.id.startswith(prefix))

    r.dns_system_ok = _step_ok("dns_system")
    r.dns_public_ok = any(s.ok for s in result.steps
                          if s.id.startswith("dns_") and not s.id.startswith("dns_system"))
    r.tcp_ok = _step_ok("tcp_roblox")
    r.https_ok = any(s.ok for s in result.steps
                     if s.id.startswith("https_") and not s.id.startswith("https_proxy"))
    r.proxy_ok = _step_ok("https_proxy")

    # ---------------------------------------------------- classification
    if not result.internet_ok:
        r.diagnosis = DIAG_NO_INTERNET
        r.solutions = [SOL_CHECK_CABLE, SOL_RESTART_ROUTER, SOL_CONTACT_ISP]
    elif not r.dns_system_ok and not r.dns_public_ok:
        r.diagnosis = DIAG_DNS_DOWN
        r.solutions = [SOL_RESTART_ROUTER, SOL_CHANGE_DNS, SOL_CONTACT_ISP]
    elif not r.dns_system_ok and r.dns_public_ok:
        r.diagnosis = DIAG_DNS_SYSTEM_BROKEN
        r.solutions = [SOL_CHANGE_DNS, SOL_RESTART_ROUTER]
    elif not r.tcp_ok:
        # DNS works, internet works, but the TCP path to Roblox itself
        # is blocked → connection-level blocking of Roblox.
        r.diagnosis = DIAG_ROBLOX_TCP_BLOCKED
        r.solutions = [SOL_VPN_OR_NETWORK, SOL_TRY_ROPROXY, SOL_CHECK_FIREWALL]
    elif not r.https_ok and r.proxy_ok:
        # Roblox HTTPS filtered while a mirror over the same path works.
        r.diagnosis = DIAG_ROBLOX_HTTPS_BLOCKED
        r.solutions = [SOL_TRY_ROPROXY, SOL_VPN_OR_NETWORK, SOL_CHECK_FIREWALL]
    elif not r.https_ok:
        r.diagnosis = DIAG_ROBLOX_HTTPS_BLOCKED
        r.solutions = [SOL_CHECK_FIREWALL, SOL_VPN_OR_NETWORK, SOL_WAIT_RETRY]
    elif r.https_ok and not r.tcp_ok:
        r.diagnosis = DIAG_ROBLOX_PARTIAL
        r.solutions = [SOL_TRY_ROPROXY, SOL_WAIT_RETRY]
    else:
        # Some HTTPS endpoint returned a server-side failure?
        statuses = [s.detail.get("status") for s in result.steps
                    if s.id.startswith("https_") and s.detail.get("status")]
        if statuses and all(st >= 500 for st in statuses if st):
            r.diagnosis = DIAG_ROBLOX_SERVICE
            r.solutions = [SOL_WAIT_RETRY]
        else:
            r.diagnosis = DIAG_ALL_GOOD
            r.solutions = [SOL_NONE]
    return r


# --------------------------------------------------------------- export
def _mask_step(step: dict) -> dict:
    out = dict(step)
    detail = dict(out.get("detail", {}))
    if "addresses" in detail:
        detail["addresses"] = [mask_ip(a) for a in detail["addresses"]]
    if "host" in detail:
        detail["host"] = mask_ip(detail["host"])
    out["detail"] = detail
    return out


def export_json(report: Report, path: str, *, app_version: str = config.APP_VERSION) -> None:
    """Write the report as shareable JSON. Every IP is MASKED first
    (Spec §4): the file never contains a full address."""
    payload = {
        "app": config.APP_NAME,
        "version": app_version,
        "exported_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "report": report.as_dict(),
    }
    payload["report"]["steps"] = [_mask_step(s) for s in report.steps]
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
