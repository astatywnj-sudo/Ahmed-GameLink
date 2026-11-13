"""Shared, real UI widgets.

Nothing here is decorative filler: every widget is used by a page.
The placeholder page exists to honour Spec section 3 ("no fake UI —
features not implemented are hidden or disabled with an
'Under development' message").
"""

from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

import i18n
from ui.i18n_mixin import TranslatableMixin


def fmt_bytes(n: int) -> str:
    """Human-readable byte counts used across data-usage displays."""
    n = max(0, int(n))
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / (1024 * 1024):.2f} MB"


class PlaceholderPage(QWidget, TranslatableMixin):
    """Shown for sections whose engine is not implemented yet. It makes
    the not-implemented state explicit instead of faking results."""

    def __init__(self, page_key: str, parent=None) -> None:
        QWidget.__init__(self, parent)
        self._init_i18n()
        self._page_key = page_key

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(10)

        self.title_label = QLabel(self)
        self.title_label.setObjectName("pageH1")

        self.badge = QLabel(self)
        self.badge.setObjectName("muted")

        self.text_label = QLabel(self)
        self.text_label.setObjectName("muted")
        self.text_label.setWordWrap(True)

        layout.addWidget(self.title_label)
        layout.addWidget(self.badge)
        layout.addSpacing(6)
        layout.addWidget(self.text_label)
        layout.addStretch(1)

        self.bind_text(self.title_label, "placeholder.title")
        self.bind_text(self.badge, "common.developing")
        self.bind_text(self.text_label, "placeholder.text")
        self.retranslate_dynamic()

    def retranslate_dynamic(self) -> None:
        self.title_label.setText(i18n.tr("placeholder.title", page=i18n.tr(self._page_key)))
