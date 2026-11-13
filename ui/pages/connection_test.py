"""Connection Test page — live sequential steps + the Arabic report.

Real behaviors only:
- rows appear as steps actually start (engine → worker → signals);
- Cancel works while running (immediate, see core/cancel.py);
- Retry re-runs; Export writes a JSON report with all IPs masked;
- the report retranslates instantly when the user switches language.
"""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

import i18n
from core.privacy import mask_ip
from core.report import build_report, export_json
from ui.i18n_mixin import TranslatableMixin
from ui.widgets import fmt_bytes

STEP_KEYS = {    "internet": "conn.step.internet",
    "dns_system": "conn.step.dns_system",
    "tcp_roblox": "conn.step.tcp",
    "https_web": "conn.step.https_web",
    "https_apis": "conn.step.https_apis",
    "https_client_api": "conn.step.https_client_api",
    "https_proxy_web": "conn.step.https_proxy",
}


class ConnectionTestPage(QWidget, TranslatableMixin):
    cancel_requested = Signal()

    def __init__(self, parent=None) -> None:
        QWidget.__init__(self, parent)
        self._init_i18n()
        self._report = None          # core.report.Report
        self._rows: dict[str, QLabel] = {}
        self._data_sent = 0
        self._data_received = 0
        self._running = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(36, 28, 36, 20)
        layout.setSpacing(10)

        self.h1 = QLabel(self)
        self.h1.setObjectName("pageH1")

        self.status_label = QLabel(self)
        self.status_label.setObjectName("muted")

        self.progress = QProgressBar(self)
        self.progress.setRange(0, 100)
        self.progress.setVisible(False)

        self.steps_group = QGroupBox(self)
        self.steps_layout = QVBoxLayout(self.steps_group)
        self.steps_layout.setSpacing(6)

        self.report_group = QGroupBox(self)
        report_layout = QVBoxLayout(self.report_group)
        self.report_label = QLabel(self.report_group)
        self.report_label.setWordWrap(True)
        self.report_label.setTextInteractionFlags(
            self.report_label.textInteractionFlags()
            | self.report_label.textInteractionFlags().TextSelectableByMouse)
        report_layout.addWidget(self.report_label)

        buttons_row = QHBoxLayout()
        self.cancel_button = QPushButton(self)
        self.cancel_button.clicked.connect(self.cancel_requested.emit)
        self.cancel_button.setVisible(False)
        self.retry_button = QPushButton(self)
        self.retry_button.setEnabled(False)
        self.export_button = QPushButton(self)
        self.export_button.setEnabled(False)
        buttons_row.addWidget(self.cancel_button)
        buttons_row.addWidget(self.retry_button)
        buttons_row.addWidget(self.export_button)
        buttons_row.addStretch(1)

        self.data_label = QLabel(self)
        self.data_label.setObjectName("muted")

        layout.addWidget(self.h1)
        layout.addWidget(self.status_label)
        layout.addWidget(self.progress)
        layout.addWidget(self.steps_group)
        layout.addWidget(self.report_group)
        layout.addLayout(buttons_row)
        layout.addWidget(self.data_label)
        layout.addStretch(1)

        self.bind_text(self.h1, "sidebar.connection_test")
        self.bind_text(self.cancel_button, "conn.btn.cancel")
        self.bind_tooltip(self.cancel_button, "conn.btn.cancel_tip")
        self.bind_text(self.retry_button, "conn.btn.retry")
        self.bind_tooltip(self.retry_button, "conn.btn.retry_tip")
        self.bind_text(self.export_button, "conn.btn.export")
        self.bind_tooltip(self.export_button, "conn.btn.export_tip")
        self._render_report()

    # ------------------------------------------------------------ run state
    def begin_run(self) -> None:
        self._running = True
        self._report = None
        self._rows = {}
        self._data_sent = 0
        self._data_received = 0
        while self.steps_layout.count():
            item = self.steps_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.progress.setValue(0)
        self.progress.setVisible(True)
        self.cancel_button.setVisible(True)
        self.retry_button.setEnabled(False)
        self.export_button.setEnabled(False)
        self.status_label.setText(i18n.tr("conn.status.running"))
        self._render_report()

    def on_step_started(self, step_id: str) -> None:
        row = QLabel(self)
        row.setText(self._running_text(step_id))
        row.setObjectName("stepRun")
        self._rows[step_id] = row
        self.steps_layout.addWidget(row)

    def on_step_finished(self, step) -> None:
        row = self._rows.get(step.id)
        if row is None:
            row = QLabel(self)
            self._rows[step.id] = row
            self.steps_layout.addWidget(row)
        row.setText(self._result_text(step))
        row.setObjectName("stepOk" if step.ok else "stepFail")
        row.style().unpolish(row)
        row.style().polish(row)

    def on_progress(self, pct: int) -> None:
        self.progress.setValue(pct)

    def show_result(self, diag) -> None:
        self._running = False
        self.progress.setVisible(False)
        self.cancel_button.setVisible(False)
        self.retry_button.setEnabled(True)
        self.export_button.setEnabled(True)
        self._data_sent = diag.data.get("last_check_sent", 0)
        self._data_received = diag.data.get("last_check_received", 0)
        self._report = build_report(diag)
        if diag.cancelled:
            self.status_label.setText(i18n.tr("conn.status.cancelled"))
        else:
            self.status_label.setText(
                i18n.tr("conn.status.done", seconds=diag.elapsed_s))
        self._render_report()
        self._render_data_line()

    def on_cancelled(self) -> None:
        self._running = False
        self.progress.setVisible(False)
        self.cancel_button.setVisible(False)
        self.retry_button.setEnabled(True)
        self.export_button.setEnabled(True)
        self.status_label.setText(i18n.tr("conn.status.cancelled"))
        self._render_report()

    def on_engine_error(self, message: str) -> None:
        self._running = False
        self.progress.setVisible(False)
        self.cancel_button.setVisible(False)
        self.status_label.setText(i18n.tr("conn.status.error", message=message))

    # ------------------------------------------------------------ rendering
    def _step_name(self, step_id: str) -> str:
        if step_id.startswith("dns_") and step_id not in STEP_KEYS:
            server = step_id[len("dns_"):]
            label = i18n.tr("conn.step.dns")
            return f"{label} — {mask_ip(server)}"
        return i18n.tr(STEP_KEYS.get(step_id, step_id))

    def _running_text(self, step_id: str) -> str:
        return f"• {self._step_name(step_id)} — {i18n.tr('conn.row.running')}"

    def _result_text(self, step) -> str:
        name = self._step_name(step.id)
        if step.ok:
            ms = f" {step.elapsed_ms:.0f} ms" if step.elapsed_ms else ""
            return f"✓ {name}{ms}"
        error = step.error or "failed"
        return f"✗ {name} — {error}"

    def _render_report(self) -> None:
        if self._report is None:
            self.report_label.setText(i18n.tr("conn.report.empty"))
            return
        r = self._report
        diagnosis = i18n.tr(f"report.diag.{r.diagnosis}")
        solutions = "\n".join(
            "•  " + i18n.tr(f"report.solution.{code}") for code in r.solutions)
        self.report_label.setText(
            f"{diagnosis}\n\n{i18n.tr('conn.report.solutions_title')}\n"
            f"{solutions}\n\n{i18n.tr('report.note.honest')}")

    def _render_data_line(self) -> None:
        if self._report is None:
            self.data_label.setText("")
            return
        self.data_label.setText(i18n.tr(
            "conn.data_usage",
            sent=fmt_bytes(self._data_sent),
            received=fmt_bytes(self._data_received)))

    # ------------------------------------------------------------- export
    def export_report(self) -> None:
        if self._report is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, i18n.tr("conn.btn.export"), "ahmed-gamelink-report.json",
            "JSON (*.json)")
        if not path:
            return
        try:
            export_json(self._report, path)
            QMessageBox.information(self, i18n.tr("conn.btn.export"),
                                    i18n.tr("conn.export.done", path=path))
        except OSError as exc:
            QMessageBox.warning(self, i18n.tr("conn.btn.export"),
                                i18n.tr("conn.export.failed", error=str(exc)))

    # ------------------------------------------------------- retranslate
    @property
    def is_running(self) -> bool:
        return self._running

    def retranslate_dynamic(self) -> None:
        self._render_report()
        self._render_data_line()
