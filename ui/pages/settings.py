"""Settings page — language switching applied instantly (no restart).

Only real, working settings are shown (Spec section 3: no fake controls):
- Language: Arabic (RTL, default) / English (LTR) — applied immediately.
- Restore defaults: clears the local settings file.
The privacy group states the guarantees from Spec section 4.
"""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

import i18n
from app_state import AppState
from ui.i18n_mixin import TranslatableMixin


class SettingsPage(QWidget, TranslatableMixin):
    language_changed = Signal(str)

    def __init__(self, state: AppState, parent=None) -> None:
        QWidget.__init__(self, parent)
        self._init_i18n()
        self._state = state

        layout = QVBoxLayout(self)
        layout.setContentsMargins(36, 32, 36, 24)
        layout.setSpacing(14)

        self.h1 = QLabel(self)
        self.h1.setObjectName("pageH1")
        layout.addWidget(self.h1)

        # ------------------------------------------------------- language
        lang_group = QGroupBox(self)
        lang_layout = QVBoxLayout(lang_group)
        lang_layout.setSpacing(8)

        self.lang_label = QLabel(lang_group)
        self.lang_label.setObjectName("muted")

        combo_row = QHBoxLayout()
        self.lang_combo = QComboBox(lang_group)
        self.lang_combo.setToolTip("")  # bound below; guards against empty tip
        combo_row.addWidget(self.lang_combo)
        combo_row.addStretch(1)
        lang_layout.addWidget(self.lang_label)
        lang_layout.addLayout(combo_row)

        # Combo entries: index 0 = Arabic, 1 = English.
        self.lang_combo.addItem("")
        self.lang_combo.addItem("")
        self.lang_combo.currentIndexChanged.connect(self._on_language_selected)

        reset_row = QHBoxLayout()
        self.reset_button = QPushButton(lang_group)
        self.reset_button.clicked.connect(self._on_reset)
        reset_row.addWidget(self.reset_button)
        reset_row.addStretch(1)
        lang_layout.addLayout(reset_row)

        layout.addWidget(lang_group)

        # -------------------------------------------------------- privacy
        privacy_group = QGroupBox(self)
        privacy_layout = QVBoxLayout(privacy_group)
        self.privacy_label = QLabel(privacy_group)
        self.privacy_label.setObjectName("muted")
        self.privacy_label.setWordWrap(True)
        privacy_layout.addWidget(self.privacy_label)
        layout.addWidget(privacy_group)
        layout.addStretch(1)

        # i18n bindings (refreshed on language change)
        self.bind_text(self.h1, "sidebar.settings")
        self.bind_title(lang_group, "settings.language_title")
        self.bind_text(self.lang_label, "settings.language_label")
        self.bind_tooltip(self.lang_combo, "settings.language_combo_tip")
        self.bind_text(self.reset_button, "settings.reset")
        self.bind_tooltip(self.reset_button, "settings.reset_tooltip")
        self.bind_title(privacy_group, "settings.privacy_title")
        self.bind_text(self.privacy_label, "settings.privacy_text")

        self._sync_combo_from_state()

    # -------------------------------------------------------------- combo
    def _sync_combo_from_state(self) -> None:
        self.lang_combo.blockSignals(True)
        self.lang_combo.setCurrentIndex(0 if i18n.current() == "ar" else 1)
        self.lang_combo.blockSignals(False)

    def _on_language_selected(self, index: int) -> None:
        lang = "ar" if index == 0 else "en"
        if lang == i18n.current():
            return
        self._state.set("language", lang)
        self.language_changed.emit(lang)

    # -------------------------------------------------------------- reset
    def _on_reset(self) -> None:
        answer = QMessageBox.question(
            self,
            i18n.tr("settings.reset_title"),
            i18n.tr("settings.reset_message"),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        self._state.reset()
        i18n.load(self._state.settings["language"])
        self._sync_combo_from_state()
        # "ar" is always the default; emit only if language actually differs.
        self.language_changed.emit(i18n.current())

    # called by MainWindow when language changes (incl. from here)
    def retranslate_dynamic(self) -> None:
        self._sync_combo_from_state()
