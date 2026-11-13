"""Ahmed GameLink — entry point.

Keeps startup logic minimal: load user settings, load translations,
apply theme/RTL, show the main window.

No background services, no timers, no sockets here (Spec section 8.1).
"""

import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

import i18n
from app_state import AppState
from ui.main_window import MainWindow
from ui.theme import apply_theme, set_language_direction


def main() -> int:
    state = AppState()
    i18n.load(state.settings["language"])

    app = QApplication(sys.argv)
    app.setApplicationName("Ahmed GameLink")
    app.setApplicationVersion("0.1.0")
    set_language_direction(app, i18n.current())
    apply_theme(app)

    window = MainWindow(state)
    window.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
