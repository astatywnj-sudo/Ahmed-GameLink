"""Translatable page mixin — runtime language switching without restart.

Every page binds its static texts here once, and `retranslate()` refreshes
all of them when the user switches language in Settings (Spec section 3).
This keeps pages free of duplicated refresh logic and guarantees no text
is left in the previous language.
"""

import i18n


class TranslatableMixin:
    def _init_i18n(self) -> None:
        self._i18n_binds: list = []

    def _bind(self, key: str, setter) -> None:
        setter(i18n.tr(key))
        self._i18n_binds.append((setter, key))

    def bind_text(self, widget, key: str) -> None:
        self._bind(key, widget.setText)

    def bind_tooltip(self, widget, key: str) -> None:
        self._bind(key, widget.setToolTip)

    def bind_placeholder(self, widget, key: str) -> None:
        self._bind(key, widget.setPlaceholderText)

    def bind_title(self, group, key: str) -> None:
        self._bind(key, group.setTitle)

    def retranslate(self) -> None:
        for setter, key in self._i18n_binds:
            setter(i18n.tr(key))
        self.retranslate_dynamic()

    def retranslate_dynamic(self) -> None:
        """Override for texts that depend on runtime values (e.g. version)."""
