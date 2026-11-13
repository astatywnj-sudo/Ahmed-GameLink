"""Data Usage page (Spec §8.3 — exactly):

- ONLY the bytes produced by Ahmed GameLink itself during checks
  (requests + responses), measured at socket level by the counting
  wrappers. Never Roblox traffic, never other apps, no Npcap/WinDivert,
  no admin rights.
- Shows "last check" AND "session total" separately.
- Event-driven updates ONLY (no timers, no polling — Spec §8.1):
  refresh() is called when the user opens the page and when a check
  finishes (MainWindow signal).
"""

from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

import i18n
from core.data_counter import SESSION_COUNTER
from ui.i18n_mixin import TranslatableMixin
from ui.widgets import fmt_bytes


class DataUsagePage(QWidget, TranslatableMixin):
    def __init__(self, parent=None) -> None:
        QWidget.__init__(self, parent)
        self._init_i18n()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(36, 28, 36, 20)
        layout.setSpacing(12)

        self.h1 = QLabel(self)
        self.h1.setObjectName("pageH1")

        self.explain_label = QLabel(self)
        self.explain_label.setObjectName("muted")
        self.explain_label.setWordWrap(True)

        layout.addWidget(self.h1)
        layout.addWidget(self.explain_label)

        # ------------------------------------------------- last-check card
        last_group = QGroupBox(self)
        last_layout = QVBoxLayout(last_group)
        self.last_caption = QLabel(last_group)
        self.last_caption.setObjectName("muted")
        self.last_value = QLabel(last_group)
        self.last_value.setObjectName("metricValue")
        last_layout.addWidget(self.last_caption)
        last_layout.addWidget(self.last_value)
        layout.addWidget(last_group)

        # ------------------------------------------------ session card
        session_group = QGroupBox(self)
        session_layout = QVBoxLayout(session_group)
        self.session_caption = QLabel(session_group)
        self.session_caption.setObjectName("muted")
        self.session_value = QLabel(session_group)
        self.session_value.setObjectName("metricValue")
        session_layout.addWidget(self.session_caption)
        self.session_value.setText("0 B / 0 B — 0 B")
        session_layout.addWidget(self.session_value)
        layout.addWidget(session_group)

        # ------------------------------------------------------- buttons
        buttons_row = QHBoxLayout()
        self.refresh_button = QPushButton(self)
        self.refresh_button.clicked.connect(self.refresh)
        self.reset_button = QPushButton(self)
        self.reset_button.clicked.connect(self._on_reset)
        buttons_row.addWidget(self.refresh_button)
        buttons_row.addWidget(self.reset_button)
        buttons_row.addStretch(1)
        layout.addLayout(buttons_row)

        self.note_label = QLabel(self)
        self.note_label.setObjectName("disclaimer")
        self.note_label.setWordWrap(True)
        layout.addWidget(self.note_label)
        layout.addStretch(1)

        self.bind_text(self.h1, "sidebar.data_usage")
        self.bind_text(self.explain_label, "data.explain")
        self.bind_text(self.last_caption, "data.last_caption")
        self.bind_text(self.session_caption, "data.session_caption")
        self.bind_text(self.refresh_button, "data.refresh")
        self.bind_tooltip(self.refresh_button, "data.refresh_tip")
        self.bind_text(self.reset_button, "data.reset")
        self.bind_tooltip(self.reset_button, "data.reset_tip")
        self.bind_text(self.note_label, "data.note")
        self.refresh()

    # ------------------------------------------------------------ refresh
    def refresh(self) -> None:
        snap = SESSION_COUNTER.snapshot()
        self.last_value.setText(i18n.tr(
            "data.value_line",
            sent=fmt_bytes(snap["last_check_sent"]),
            received=fmt_bytes(snap["last_check_received"]),
            total=fmt_bytes(snap["last_check_sent"] + snap["last_check_received"])))
        self.session_value.setText(i18n.tr(
            "data.value_line",
            sent=fmt_bytes(snap["session_sent"]),
            received=fmt_bytes(snap["session_received"]),
            total=fmt_bytes(snap["session_sent"] + snap["session_received"])))

    def _on_reset(self) -> None:
        answer = QMessageBox.question(
            self,
            i18n.tr("data.reset_title"),
            i18n.tr("data.reset_message"),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        SESSION_COUNTER.reset_session()
        self.refresh()
