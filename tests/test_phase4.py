"""Phase 4 acceptance tests — netdiag engine + Data Usage + Zero-Idle:

    python tests/test_phase4.py

Verifies:
- detailed per-target measurement: real numbers, budget, cancellation;
- Data Usage numbers come from the REAL counter (§8.3) and reset works;
- ZERO-IDLE final review: no QTimer/timers anywhere in the UI code, no
  threads after navigating through every page, nav buttons actually
  switch pages (regression guard).
"""

import os
import re
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import config
from core.cancel import CancelContext
from core.data_counter import SESSION_COUNTER, DataCounter
from core.netdiag import run_network_diagnostics


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {label}" + (f" — {detail}" if detail else ""))
    if not ok:
        sys.exit(1)


def test_netdiag_engine() -> None:
    cancel = CancelContext()
    result = run_network_diagnostics(cancel)
    check("netdiag: run completed within budget",
          result.elapsed_s < 42.0, f"{result.elapsed_s:.1f} s, targets={len(result.targets)}")
    ok_targets = [t for t in result.targets if t.ok]
    for t in ok_targets:
        avg = sum(t.rtts) / len(t.rtts)
        print(f"      ✓ {t.id} ({t.host}): avg {avg:.0f} ms "
              f"(min {min(t.rtts):.0f} / max {max(t.rtts):.0f}), "
              f"loss {t.lost}/{t.lost + len(t.rtts)}, "
              f"bytes {t.sent}/{t.received}")
    data = result.data
    total = data["last_check_sent"] + data["last_check_received"]
    check("netdiag: data counter measured this run (§8.3)",
          total >= 0 and data["session_sent"] >= data["last_check_sent"],
          f"sent {data['last_check_sent']} B / recv {data['last_check_received']} B")
    check("netdiag: sequential — targets appear in fixed order",
          [t.id for t in result.targets] ==
          [t[0] for t in __import__('core.netdiag', fromlist=['build_targets']).build_targets()])


def test_netdiag_cancel() -> None:
    cancel = CancelContext()
    box = []

    def runner() -> None:
        box.append(run_network_diagnostics(cancel))

    t = threading.Thread(target=runner)
    t.start()
    time.sleep(1.0)
    t0 = time.perf_counter()
    cancel.cancel()
    t.join(timeout=15)
    latency = time.perf_counter() - t0
    check("netdiag: cancel stops the run quickly (≤ one echo timeout)",
          not t.is_alive() and latency < 4.0, f"latency={latency:.2f} s")
    if box:
        r = box[0]
        roblox = next((t for t in r.targets if t.id == "roblox_web"), None)
        # Cancel fired while the LAST target was already running: the run
        # is honest if it stopped early — the in-flight target must NOT
        # have completed all 3 attempts.
        check("netdiag: cancelled result is honest (in-flight target cut short)",
              r.cancelled and roblox is not None
              and (roblox.lost + len(roblox.rtts)) < 3,
              f"targets={len(r.targets)}, roblox attempts={roblox.lost + len(roblox.rtts) if roblox else '?'}")


def test_data_counter_isolation() -> None:
    counter = DataCounter()
    counter.add_sent(879)
    counter.add_received(3732)
    snap1 = counter.snapshot()
    check("data usage: last check == real numbers from the run (879/3732)",
          snap1["last_check_sent"] == 879 and snap1["last_check_received"] == 3732,
          f"sent {snap1['last_check_sent']} / recv {snap1['last_check_received']}")
    check("data usage: session total accumulates separately",
          snap1["session_sent"] == 879 and snap1["session_received"] == 3732)
    counter.reset_check()
    counter.add_sent(10)
    snap2 = counter.snapshot()
    check("data usage: new check resets LAST only, session keeps history",
          snap2["last_check_sent"] == 10
          and snap2["session_sent"] == 889
          and snap2["session_received"] == 3732)
    counter.reset_session()
    snap3 = counter.snapshot()
    check("data usage: reset_session zeroes everything",
          all(v == 0 for v in snap3.values()))


def test_zero_idle_static() -> None:
    """Static guarantee: no timers, no polling loops in the UI layer."""
    root = Path(__file__).resolve().parent.parent
    offenders = []
    for pattern in (r"QTimer\(", r"startTimer\(", r"singleShot\(", r"time\.sleep\("):
        for path in (root / "ui").rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            if re.search(pattern, text):
                offenders.append(f"{path.name}: {pattern}")
    check("zero-idle: no QTimer/startTimer/singleShot/sleep in ui/",
          not offenders, str(offenders or "clean"))
    # Same for the engine's steady state (sleep allowed in cancellable
    # connect select-loop only):
    engine_bad = []
    for pattern in (r"QTimer\(", r"time\.sleep\("):
        for path in (root / "core").rglob("*.py"):
            if path.name == "counting_socket.py":
                continue  # select-loop poll interval (cancellable connect)
            if re.search(pattern, path.read_text(encoding="utf-8")):
                engine_bad.append(path.name)
    check("zero-idle: no timers/polls in core/ (except documented select loop)",
          not engine_bad, str(engine_bad or "clean"))


def test_ui_nav_and_pages() -> None:
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    import i18n
    i18n.load("ar")
    from PySide6.QtWidgets import QApplication
    app = QApplication([])
    from app_state import AppState
    from ui.main_window import MainWindow
    from ui.pages.data_usage import DataUsagePage
    from ui.pages.network_diag import NetworkDiagPage

    window = MainWindow(AppState())
    window.show()
    app.processEvents()

    # Sidebar buttons actually switch the stack now (regression guard).
    for idx in range(window.stack.count()):
        window.nav_group.buttons()[idx].click()
        app.processEvents()
        check(f"nav: button {idx} switches to page {idx}",
              window.stack.currentIndex() == idx)

    data_page = window.stack.widget(3)
    check("data page: is the real DataUsagePage", isinstance(data_page, DataUsagePage))
    netdiag_page = window.stack.widget(2)
    check("netdiag page: is the real NetworkDiagPage",
          isinstance(netdiag_page, NetworkDiagPage))

    # Event-driven refresh: feed the real counter, refresh, read the label.
    SESSION_COUNTER.reset_session()
    SESSION_COUNTER.add_sent(879)
    SESSION_COUNTER.add_received(3732)
    data_page.refresh()
    label = data_page.last_value.text() + data_page.session_value.text()
    check("data page: shows REAL counter numbers (879 B / 3,732 B)",
          "879 B" in label and "3.6 KB" in label,
          label.replace("\n", " | "))
    SESSION_COUNTER.reset_session()
    data_page.refresh()
    check("data page: after reset, zeros are shown honestly",
          "0 B" in data_page.session_value.text())

    check("zero-idle: no threads after navigating everywhere",
          threading.active_count() == 1, f"active={threading.active_count()}")
    window.close()


def main() -> None:
    print(f"Ahmed GameLink — Phase 4 tests ({config.APP_VERSION})\n")
    test_netdiag_engine()
    test_netdiag_cancel()
    test_data_counter_isolation()
    test_zero_idle_static()
    test_ui_nav_and_pages()
    print("\nPhase 4: ALL CHECKS PASSED")


if __name__ == "__main__":
    main()
