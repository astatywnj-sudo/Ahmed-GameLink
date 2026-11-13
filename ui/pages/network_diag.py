"""Network Diagnostics page — per-target latency/loss measurements.

Real engine (core/netdiag.py): sequential ICMP, 3 echoes per target,
hard budget, cancellable. Live rows like the Connection Test page, and
results refresh the Data Usage page when the run completes.
"""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

import i18n
from core.privacy import mask_ip
from ui.i18n_mixin import TranslatableMixin

TARGET_KEYS = {
    "dns_system": "netdiag.target.dns_system",
    "dns_cloudflare": "netdiag.target.dns_cloudflare",
    "dns_google": "netdiag.target.dns_google",
    "dns_quad9": "netdiag.target.dns_quad9",
    "roblox_web": "netdiag.target.roblox_web",
}


def _target_name(target_id: str, host: str) -> str:
    label = i18n.tr(TARGET_KEYS.get(target_id, target_id))
    return f"{label} ({mask_ip(host)})"


class NetworkDiagPage(QWidget, TranslatableMixin):
    start_requested = Signal()
    cancel_requested = Signal()

    def __init__(self, parent=None) -> None:
        QWidget.__init__(self, parent)
        self._init_i18n()
        self._running = False
        self._rows: dict[str, QLabel] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(36, 28, 36, 20)
        layout.setSpacing(10)

        self.h1 = QLabel(self)
        self.h1.setObjectName("pageH1")

        self.explain_label = QLabel(self)
        self.explain_label.setObjectName("muted")
        self.explain_label.setWordWrap(True)

        self.status_label = QLabel(self)
        self.status_label.setObjectName("muted")

        self.progress = QProgressBar(self)
        self.progress.setRange(0, 100)
        self.progress.setVisible(False)

        self.results_group = QGroupBox(self)
        self.results_layout = QVBoxLayout(self.results_group)
        self.results_layout.setSpacing(6)

        buttons_row = QHBoxLayout()
        self.start_button = QPushButton(self)
        self.start_button.clicked.connect(self.start_requested.emit)
        self.cancel_button = QPushButton(self)
        self.cancel_button.clicked.connect(self.cancel_requested.emit)
        self.cancel_button.setVisible(False)
        buttons_row.addWidget(self.start_button)
        buttons_row.addWidget(self.cancel_button)
        buttons_row.addStretch(1)

        layout.addWidget(self.h1)
        layout.addWidget(self.explain_label)
        layout.addWidget(self.results_group)
        layout.addWidget(self.status_label)
        layout.addWidget(self.progress)
        layout.addLayout(buttons_row)
        layout.addStretch(1)

        self.bind_text(self.h1, "sidebar.network_diag")
        self.bind_text(self.explain_label, "netdiag.explain")
        self.bind_text(self.start_button, "netdiag.start")
        self.bind_tooltip(self.start_button, "netdiag.start_tip")
        self.bind_text(self.cancel_button, "conn.btn.cancel")
        self.bind_tooltip(self.cancel_button, "conn.btn.cancel_tip")

    # ------------------------------------------------------------ run state
    def begin_run(self) -> None:
        self._running = True
        self._rows = {}
        while self.results_layout.count():
            item = self.results_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.progress.setValue(0)
        self.progress.setVisible(True)
        self.cancel_button.setVisible(True)
        self.start_button.setEnabled(False)
        self.status_label.setText(i18n.tr("netdiag.status.running"))

    def on_target_started(self, target_id: str, host: str) -> None:
        row = QLabel(self)
        row.setObjectName("stepRun")
        row.setText(f"• {_target_name(target_id, host)} — {i18n.tr('conn.row.running')}")
        self._rows[target_id] = row
        self.results_layout.addWidget(row)

    def on_target_finished(self, t) -> None:
        row = self._rows.get(t.id)
        if row is None:
            row = QLabel(self)
            self._rows[t.id] = row
            self.results_layout.addWidget(row)
        if not t.rtts and not t.ok:
            reason = t.error or "failed"
            row.setText(f"✗ {_target_name(t.id, t.host)} — {reason}")
            row.setObjectName("stepFail")
        else:
            avg = sum(t.rtts) / len(t.rtts)
            row.setText(i18n.tr(
                "netdiag.row.result", name=_target_name(t.id, t.host),
                avg=f"{avg:.0f}", mn=f"{min(t.rtts):.0f}", mx=f"{max(t.rtts):.0f}",
                lost=t.lost, total=t.lost + len(t.rtts)))
            row.setObjectName("stepOk")
        row.style().unpolish(row)
        row.style().polish(row)

    def show_result(self, result) -> None:
        self._running = False
        self.progress.setVisible(False)
        self.cancel_button.setVisible(False)
        self.start_button.setEnabled(True)
        if result.cancelled:
            self.status_label.setText(i18n.tr("conn.status.cancelled"))
        else:
            self.status_label.setText(
                i18n.tr("netdiag.status.done", seconds=result.elapsed_s))
        for t in result.targets:
            if t.id not in self._rows:
                self.on_target_finished(t)

    def on_engine_error(self, message: str) -> None:
        self._running = False
        self.progress.setVisible(False)
        self.cancel_button.setVisible(False)
        self.start_button.setEnabled(True)
        self.status_label.setText(i18n.tr("conn.status.error", message=message))

    @property
    def is_running(self) -> bool:
        return self._running
