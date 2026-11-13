"""Home page — hosts the smart Diagnostics entry point (Spec section 5).

The Start Diagnostics button is REAL from Phase 3: it emits
`start_requested` and MainWindow launches the engine worker. While a
check runs the button disables itself (honest UI state).
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

from ui.i18n_mixin import TranslatableMixin


class HomePage(QWidget, TranslatableMixin):
    start_requested = Signal()

    def __init__(self, parent=None) -> None:
        QWidget.__init__(self, parent)
        self._init_i18n()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(36, 32, 36, 24)
        layout.setSpacing(12)

        self.title_label = QLabel(self)
        self.title_label.setObjectName("homeTitle")

        self.subtitle_label = QLabel(self)
        self.subtitle_label.setObjectName("homeSubtitle")
        self.subtitle_label.setWordWrap(True)

        layout.addSpacing(10)
        layout.addWidget(self.title_label)
        layout.addWidget(self.subtitle_label)
        layout.addSpacing(18)

        # Smart diagnostics button — starts the real engine (Phase 3).
        self.start_button = QPushButton(self)
        self.start_button.setObjectName("primary")
        self.start_button.setEnabled(True)
        self.start_button.setCursor(QCursor(Qt.PointingHandCursor))
        self.start_button.clicked.connect(self.start_requested.emit)

        self.note_label = QLabel(self)
        self.note_label.setObjectName("muted")
        self.note_label.setWordWrap(True)

        self.disclaimer_label = QLabel(self)
        self.disclaimer_label.setObjectName("disclaimer")
        self.disclaimer_label.setWordWrap(True)

        layout.addWidget(self.start_button)
        layout.addSpacing(8)
        layout.addWidget(self.note_label)
        layout.addWidget(self.disclaimer_label)
        layout.addStretch(1)

        self.bind_text(self.title_label, "home.title")
        self.bind_text(self.subtitle_label, "home.subtitle")
        self.bind_text(self.start_button, "home.start")
        self.bind_tooltip(self.start_button, "home.start_tooltip")
        self.bind_text(self.note_label, "home.note")
        self.bind_text(self.disclaimer_label, "home.disclaimer")
