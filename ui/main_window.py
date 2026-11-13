"""Main window: sidebar navigation + stacked pages.

Zero-Idle compliance (Spec section 8.1):
- No timers, no polling, no sockets exist in this class.
- Language switching is a pure UI operation (no network, no disk read
  beyond loading a small translation file once per switch).
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

import i18n
from app_state import AppState
from ui.i18n_mixin import TranslatableMixin
from ui.theme import set_language_direction
from ui.widgets import PlaceholderPage
from ui.pages.about import AboutPage
from ui.pages.connection_test import ConnectionTestPage
from ui.pages.data_usage import DataUsagePage
from ui.pages.home import HomePage
from ui.pages.network_diag import NetworkDiagPage
from ui.pages.settings import SettingsPage
from worker import DiagnosticsWorker, NetDiagWorker

# Sidebar entries, in the order required by Spec section 3.
# None = the engine is not implemented yet → honest placeholder page.
_PAGES = [
    ("sidebar.home", HomePage),
    ("sidebar.connection_test", ConnectionTestPage),
    ("sidebar.network_diag", NetworkDiagPage),
    ("sidebar.data_usage", DataUsagePage),
    ("sidebar.settings", SettingsPage),
    ("sidebar.about", AboutPage),
]


class _NetDiagCancelled:
    """Minimal result shape for the edge case where the worker thread ends
    before emitting a result (should not happen; keeps the UI honest)."""

    cancelled = True
    targets: list = []


class MainWindow(QMainWindow, TranslatableMixin):
    def __init__(self, state: AppState) -> None:
        QMainWindow.__init__(self)
        self._init_i18n()
        self._state = state
        self._nav_data: list[tuple[QPushButton, str]] = []

        self.setWindowTitle("Ahmed GameLink")
        self.resize(1020, 660)
        self.setMinimumSize(880, 560)

        central = QWidget(self)
        root_layout = QHBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # ------------------------------------------------------------ sidebar
        sidebar = QFrame(central)
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(230)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(12, 16, 12, 12)
        sidebar_layout.setSpacing(4)

        self.app_title = QLabel(sidebar)
        self.app_title.setObjectName("pageH1")
        self.app_title.setAlignment(Qt.AlignCenter)
        sidebar_layout.addWidget(self.app_title)
        sidebar_layout.addSpacing(10)

        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)

        for nav_key, _factory in _PAGES:
            button = QPushButton(sidebar)
            button.setObjectName("sidebarBtn")
            button.setCheckable(True)
            button.setCursor(QCursor(Qt.PointingHandCursor))
            # Explicit id == stack index (Qt's auto-assigned ids are negative).
            self.nav_group.addButton(button, len(self._nav_data))
            self._nav_data.append((button, nav_key))
            sidebar_layout.addWidget(button)

        sidebar_layout.addStretch(1)

        # ------------------------------------------------------------- pages
        self.stack = QStackedWidget(central)
        self._page_widgets: list[tuple[QWidget, str]] = []

        for nav_key, factory in _PAGES:
            if factory is SettingsPage:
                page = factory(state)
                page.language_changed.connect(self._on_language_changed)
            elif factory is not None:
                page = factory()
            else:
                page = PlaceholderPage(nav_key)
            self.stack.addWidget(page)
            self._page_widgets.append((page, nav_key))

        root_layout.addWidget(sidebar)
        root_layout.addWidget(self.stack, 1)
        self.setCentralWidget(central)

        # i18n bindings (refreshed on language change)
        self.bind_text(self.app_title, "app.title")
        for button, nav_key in self._nav_data:
            self.bind_text(button, nav_key)
            self.bind_tooltip(button, f"{nav_key}_tip")

        # Select Home (index 0) on startup.
        self.nav_group.buttons()[0].setChecked(True)
        self.stack.setCurrentIndex(0)
        self.nav_group.idClicked.connect(self._on_nav_clicked)

        # -------------------------------------------------- diagnostics run
        self._worker: DiagnosticsWorker | None = None
        self._netdiag_worker: NetDiagWorker | None = None
        self.home_page = self.stack.widget(0)
        self.conn_page = self.stack.widget(1)
        self.netdiag_page = self.stack.widget(2)
        self.data_page = self.stack.widget(3)
        self.home_page.start_requested.connect(self._start_diagnostics)
        self.conn_page.cancel_requested.connect(self._cancel_diagnostics)
        self.conn_page.retry_button.clicked.connect(self._start_diagnostics)
        self.conn_page.export_button.clicked.connect(self.conn_page.export_report)
        self.netdiag_page.start_requested.connect(self._start_netdiag)
        self.netdiag_page.cancel_requested.connect(self._cancel_netdiag)

    # ------------------------------------------------------------- nav
    def _on_nav_clicked(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        # Event-driven refresh only: opening the Data Usage page reads the
        # counters once. No timers, no polling (Spec §8.1).
        if index == 3:
            self.data_page.refresh()

    # ---------------------------------------------------- diagnostics run
    def _start_diagnostics(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            return                          # one check at a time
        self.stack.setCurrentIndex(1)       # jump to Connection Test page
        self.conn_page.begin_run()
        self.home_page.start_button.setEnabled(False)

        self._worker = DiagnosticsWorker(self)
        self._worker.step_started.connect(self.conn_page.on_step_started)
        self._worker.step_finished.connect(self.conn_page.on_step_finished)
        self._worker.progress_changed.connect(self.conn_page.on_progress)
        self._worker.report_ready.connect(self._on_report_ready)
        self._worker.engine_error.connect(self._on_engine_error)
        self._worker.finished.connect(self._on_worker_finished)
        self._worker.start()

    def _cancel_diagnostics(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            self._worker.cancel()           # immediate (core/cancel.py)

    def _on_report_ready(self, diag) -> None:
        self.conn_page.show_result(diag)
        self.data_page.refresh()            # §8.3: numbers right after a check

    def _on_engine_error(self, message: str) -> None:
        self.conn_page.on_engine_error(message)

    def _on_worker_finished(self) -> None:
        # Re-arm the UI whatever the outcome (done / cancelled / error).
        self.home_page.start_button.setEnabled(True)
        if self.conn_page.is_running:
            self.conn_page.on_cancelled()
        self._worker = None

    # ------------------------------------------------- network diagnostics
    def _start_netdiag(self) -> None:
        if self._netdiag_worker is not None and self._netdiag_worker.isRunning():
            return
        self.netdiag_page.begin_run()
        self._netdiag_worker = NetDiagWorker(self)
        self._netdiag_worker.target_started.connect(self.netdiag_page.on_target_started)
        self._netdiag_worker.target_finished.connect(self.netdiag_page.on_target_finished)
        self._netdiag_worker.result_ready.connect(self._on_netdiag_ready)
        self._netdiag_worker.engine_error.connect(self.netdiag_page.on_engine_error)
        self._netdiag_worker.finished.connect(self._on_netdiag_worker_finished)
        self._netdiag_worker.start()

    def _cancel_netdiag(self) -> None:
        if self._netdiag_worker is not None and self._netdiag_worker.isRunning():
            self._netdiag_worker.cancel()

    def _on_netdiag_ready(self, result) -> None:
        self.netdiag_page.show_result(result)
        self.data_page.refresh()

    def _on_netdiag_worker_finished(self) -> None:
        if self.netdiag_page.is_running:
            self.netdiag_page.show_result(_NetDiagCancelled())
        self._netdiag_worker = None
        self.data_page.refresh()

    # ---------------------------------------------------------- language
    def _on_language_changed(self, lang: str) -> None:
        i18n.load(lang)
        # Apply RTL/LTR at application level so every open window flips.
        set_language_direction(QApplication.instance(), lang)
        self.retranslate_all()

    # -------------------------------------------------------- retranslate
    def retranslate_all(self) -> None:
        """Refresh every text in the window (Spec section 3: instant switch)."""
        self.retranslate()
        for page, _key in self._page_widgets:
            page.retranslate()
        # The app title also needs the window title.
        self.setWindowTitle("Ahmed GameLink")

    # ------------------------------------------------------------- close
    def closeEvent(self, event) -> None:
        # Spec §8.2: closing the app stops EVERYTHING immediately —
        # cancel any running worker and WAIT for threads to exit so
        # nothing (socket, thread) survives the process.
        for worker in (self._worker, self._netdiag_worker):
            if worker is not None and worker.isRunning():
                worker.cancel()
                worker.wait(3000)
        event.accept()
