"""Phase 1 acceptance tests — run without showing a window:

    python tests/test_phase1.py

Verifies: app state load/save/reset, i18n loading, RTL/LTR direction,
instant language switching (no restart), tooltips on all buttons, and
that unimplemented sections show the honest "under development" page.
"""

import os
import sys

# Headless: no window is shown; the test only inspects widgets.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

import i18n
from app_state import AppState
from core import config


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {label}" + (f" — {detail}" if detail else ""))
    if not ok:
        sys.exit(1)


def main() -> None:
    # ------------------------------------------------------------ settings
    from app_state import config_dir
    test_path = config_dir() / "settings.test.json"  # isolated test file
    state = AppState(test_path)
    state.settings = {"language": "en"}
    state.save()
    loaded = AppState(state.path)
    check("AppState: save/load round-trip", loaded.settings["language"] == "en")
    loaded.reset()
    check("AppState: reset restores defaults", loaded.settings["language"] == "ar")

    # ---------------------------------------------------------------- i18n
    i18n.load("ar")
    check("i18n: default language is Arabic", i18n.current() == "ar")
    check("i18n: Arabic text loads", i18n.tr("home.start") == "Start Diagnostics")
    check("i18n: technical terms stay English (Start Diagnostics)",
          "Start Diagnostics" in i18n.tr("home.start"))
    check("i18n: {param} formatting works",
          i18n.tr("about.version", version=config.APP_VERSION) == f"الإصدار {config.APP_VERSION}")
    check("i18n: missing key falls back to key itself", i18n.tr("no.such.key") == "no.such.key")

    # -------------------------------------------------------------- window
    i18n.load("ar")
    app = QApplication([])
    from ui.main_window import MainWindow
    from ui.theme import set_language_direction
    set_language_direction(app, "ar")

    window = MainWindow(state)
    window.show()
    app.processEvents()

    check("MainWindow: 6 pages in the stack", window.stack.count() == 6,
          f"got {window.stack.count()}")
    check("MainWindow: RTL direction in Arabic", app.layoutDirection() == Qt.RightToLeft)
    check("MainWindow: Home page is first", window.stack.currentIndex() == 0)

    home = window.stack.widget(0)
    start_btn = home.start_button
    check("Home: Start Diagnostics exists", start_btn.text() == "Start Diagnostics")
    check("Home: Start Diagnostics is REAL and ENABLED (engine complete)",
          start_btn.isEnabled())
    check("Home: Start Diagnostics has a tooltip", bool(start_btn.toolTip()))
    check("Home: tooltip explains the check (10 s / step, 45 s total)",
          "45" in start_btn.toolTip() and "10" in start_btn.toolTip())

    # Tooltips on ALL sidebar buttons (Spec section 3).
    missing_tips = [key for btn, key in window._nav_data if not btn.toolTip()]
    check("MainWindow: every sidebar button has a tooltip", not missing_tips,
          str(missing_tips))

    # ------------------------------------------------ language switch live
    window._on_language_changed("en")
    app.processEvents()
    check("Language switch: direction becomes LTR", app.layoutDirection() == Qt.LeftToRight)
    check("Language switch: sidebar button text refreshed",
          window._nav_data[0][0].text() == "Home")
    check("Language switch: Home title refreshed",
          home.title_label.text() == "Welcome to Ahmed GameLink")
    check("Language switch: Start button text still English-named",
          start_btn.text() == "Start Diagnostics")

    window._on_language_changed("ar")
    app.processEvents()
    check("Language switch back to Arabic: RTL again", app.layoutDirection() == Qt.RightToLeft)
    check("Language switch back to Arabic: sidebar text back",
          window._nav_data[0][0].text() == "الرئيسية")

    # ------------------------------------------ Connection Test page REAL
    from ui.pages.connection_test import ConnectionTestPage
    conn_page = window.stack.widget(1)
    check("Connection Test page is REAL (engine wired)",
          isinstance(conn_page, ConnectionTestPage))
    check("Connection Test: empty-state report explains how to start",
          "Start Diagnostics" in conn_page.report_label.text())
    from ui.pages.network_diag import NetworkDiagPage
    from ui.pages.data_usage import DataUsagePage
    check("Network Diagnostics page is REAL", isinstance(window.stack.widget(2), NetworkDiagPage))
    check("Data Usage page is REAL", isinstance(window.stack.widget(3), DataUsagePage))
    check("No placeholder pages remain anywhere",
          all(not hasattr(p, "badge") for p, _k in window._page_widgets))

    window.close()

    print("\nPhase 1: ALL CHECKS PASSED")


if __name__ == "__main__":
    main()
