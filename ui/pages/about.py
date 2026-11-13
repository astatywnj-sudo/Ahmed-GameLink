"""About page — identity, MIT license, disclaimer and privacy promises
(Spec sections 4 and 6). All statements here are enforced by the code:
no telemetry, no system changes, masked IPs in reports (implemented in
later phases via core/privacy.py)."""

from PySide6.QtWidgets import QGroupBox, QLabel, QScrollArea, QVBoxLayout, QWidget

import i18n
from core import config
from ui.i18n_mixin import TranslatableMixin


class AboutPage(QScrollArea, TranslatableMixin):
    def __init__(self, parent=None) -> None:
        # QScrollArea needs an inner container widget.
        QScrollArea.__init__(self, parent)
        self._init_i18n()
        self.setWidgetResizable(True)
        self.setFrameShape(QScrollArea.NoFrame)

        body = QWidget(self)
        self.setWidget(body)

        layout = QVBoxLayout(body)
        layout.setContentsMargins(36, 32, 36, 24)
        layout.setSpacing(14)

        self.h1 = QLabel(body)
        self.h1.setObjectName("pageH1")

        self.version_label = QLabel(body)
        self.version_label.setObjectName("muted")

        self.description_label = QLabel(body)
        self.description_label.setWordWrap(True)

        license_group = QGroupBox(body)
        license_layout = QVBoxLayout(license_group)
        self.license_label = QLabel(license_group)
        self.license_label.setWordWrap(True)
        self.license_label.setObjectName("muted")
        license_layout.addWidget(self.license_label)

        disclaimer_group = QGroupBox(body)
        disclaimer_layout = QVBoxLayout(disclaimer_group)
        self.disclaimer_label = QLabel(disclaimer_group)
        self.disclaimer_label.setWordWrap(True)
        disclaimer_layout.addWidget(self.disclaimer_label)

        privacy_group = QGroupBox(body)
        privacy_layout = QVBoxLayout(privacy_group)
        self.privacy_label = QLabel(privacy_group)
        self.privacy_label.setWordWrap(True)
        privacy_layout.addWidget(self.privacy_label)

        self.copyright_label = QLabel(body)
        self.copyright_label.setObjectName("disclaimer")

        layout.addWidget(self.h1)
        layout.addWidget(self.version_label)
        layout.addWidget(self.description_label)
        layout.addWidget(license_group)
        layout.addWidget(disclaimer_group)
        layout.addWidget(privacy_group)
        layout.addWidget(self.copyright_label)
        layout.addStretch(1)

        self.bind_text(self.h1, "about.title")
        self.bind_text(self.description_label, "about.description")
        self.bind_title(license_group, "about.license_title")
        self.bind_text(self.license_label, "about.license_text")
        self.bind_title(disclaimer_group, "about.disclaimer_title")
        self.bind_text(self.disclaimer_label, "about.disclaimer_text")
        self.bind_title(privacy_group, "about.privacy_title")
        self.bind_text(self.privacy_label, "about.privacy_text")
        self.bind_text(self.copyright_label, "about.copyright")

    def retranslate_dynamic(self) -> None:
        self.version_label.setText(i18n.tr("about.version", version=config.APP_VERSION))
