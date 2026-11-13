"""Phase 3 UI integration test (headless):

    python tests/test_phase3_ui.py

Press Start Diagnostics → the worker runs → Cancel after 2 s → the UI
re-arms. Verifies the REAL wiring: signal → worker thread → page state,
plus that closing the app mid-run kills everything (Spec §8.2).
"""

import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import i18n
from PySide6.QtWidgets import QApplication


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {label}" + (f" — {detail}" if detail else ""))
    if not ok:
        sys.exit(1)


def wait_until(app, cond, timeout_s: float) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.05)
    return cond()


def main() -> None:
    i18n.load("ar")
    app = QApplication([])
    from app_state import AppState
    from ui.main_window import MainWindow

    window = MainWindow(AppState())
    window.show()
    app.processEvents()

    conn = window.conn_page
    home_btn = window.home_page.start_button

    # ---- empty state before any run
    check("empty state: report explains how to start",
          "Start Diagnostics" in conn.report_label.text())

    # ---- start a REAL run (real network), then cancel fast
    window._start_diagnostics()
    app.processEvents()
    check("start: switched to Connection Test page", window.stack.currentIndex() == 1)
    check("start: Home button disabled while running", not home_btn.isEnabled())
    check("start: worker thread is running", window._worker is not None
          and window._worker.isRunning())
    check("start: cancel button visible during run", conn.cancel_button.isVisible())

    ok = wait_until(app, lambda: len(conn._rows) >= 1, 15)
    check("start: at least one step row appeared live", ok,
          f"rows={list(conn._rows)}")

    window._cancel_diagnostics()
    ok = wait_until(app, lambda: window._worker is None, 10)
    check("cancel: worker finished quickly after Cancel", ok)
    check("cancel: Home button re-enabled", home_btn.isEnabled())
    check("cancel: page shows cancelled status",
          "إلغاء" in conn.status_label.text() or "cancel" in conn.status_label.text().lower())

    # ---- closing the app mid-run must kill everything (Spec §8.2)
    window._start_diagnostics()
    app.processEvents()
    check("restart: worker running again", window._worker is not None
          and window._worker.isRunning())
    window.close()
    ok = wait_until(app, lambda: window._worker is None
                    or not window._worker.isRunning(), 10)
    check("closeEvent: nothing survives app close", ok)

    print("\nPhase 3 UI: ALL CHECKS PASSED")


if __name__ == "__main__":
    main()
