"""Dark Mode theme (QSS) + RTL/LTR direction helper (Spec section 3).

Style targets:
- Professional dark palette, high-contrast text for small laptops.
- Segoe UI covers Arabic glyphs on Windows 10/11 out of the box.
- Technical terms stay in English even in RTL text (handled in i18n files).
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

# Palette tokens — single source of truth for the whole UI.
BG          = "#12151c"
BG_PANEL    = "#161a23"
BG_CONTROL  = "#1d2331"
BG_HOVER    = "#232a3b"
BORDER      = "#2a3142"
ACCENT      = "#2f81f7"
TEXT        = "#e6e9ef"
TEXT_MUTED  = "#8b93a7"
TEXT_DIM    = "#6b7385"
DANGER      = "#e5534b"
SUCCESS     = "#3fb950"

DARK_QSS = f"""
QWidget {{
    background-color: {BG};
    color: {TEXT};
    font-family: "Segoe UI", "Tahoma";
    font-size: 14px;
}}
QFrame#sidebar {{
    background-color: {BG_PANEL};
    border-right: 1px solid {BORDER};
}}
QLabel#homeTitle {{
    font-size: 30px; font-weight: 700; color: {TEXT};
}}
QLabel#homeSubtitle {{
    font-size: 15px; color: {TEXT_MUTED};
}}
QLabel#pageH1 {{
    font-size: 24px; font-weight: 700;
}}
QLabel#muted {{
    color: {TEXT_MUTED}; font-size: 13px;
}}
QLabel#disclaimer {{
    color: {TEXT_MUTED}; font-size: 12px;
}}
QPushButton {{
    background-color: {BG_CONTROL};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 9px 16px;
    color: {TEXT};
}}
QPushButton:hover {{ background-color: {BG_HOVER}; }}
QPushButton:pressed {{ background-color: {BORDER}; }}
QPushButton:disabled {{
    background-color: {BG_PANEL}; color: {TEXT_DIM};
    border-color: {BORDER};
}}
QPushButton#sidebarBtn {{
    text-align: right; padding: 11px 14px;
    border: none; border-radius: 8px;
    background-color: transparent;
}}
QPushButton#sidebarBtn:hover {{ background-color: {BG_HOVER}; }}
QPushButton#sidebarBtn:checked {{
    background-color: {BG_CONTROL};
    border-right: 3px solid {ACCENT};
}}
QPushButton#primary {{
    background-color: {ACCENT}; border-color: {ACCENT};
    color: #ffffff; font-weight: 600; font-size: 16px;
    padding: 14px 34px; border-radius: 10px;
}}
QPushButton#primary:disabled {{
    background-color: {BG_CONTROL}; color: {TEXT_DIM};
    border-color: {BORDER}; font-weight: 500;
}}
QGroupBox {{
    background-color: {BG_PANEL};
    border: 1px solid {BORDER};
    border-radius: 10px;
    margin-top: 14px;
    padding: 12px 10px 10px 10px;
}}
QGroupBox::title {{
    subcontrol-origin: margin; subcontrol-position: top right;
    padding: 0 6px; color: {TEXT};
}}
QComboBox {{
    background-color: {BG_CONTROL};
    border: 1px solid {BORDER};
    border-radius: 8px; padding: 7px 12px;
    min-width: 180px;
}}
QComboBox:hover {{ background-color: {BG_HOVER}; }}
QComboBox::drop-down {{ border: none; width: 26px; }}
QComboBox QAbstractItemView {{
    background-color: {BG_PANEL};
    border: 1px solid {BORDER};
    selection-background-color: {BG_HOVER};
}}
QScrollArea {{ border: none; }}
QProgressBar {{
    background-color: {BG_CONTROL};
    border: 1px solid {BORDER};
    border-radius: 6px;
    height: 12px;
    text-align: center;
}}
QProgressBar::chunk {{
    background-color: {ACCENT};
    border-radius: 5px;
}}
QLabel#stepRun {{ color: {TEXT_MUTED}; }}
QLabel#stepOk {{ color: {SUCCESS}; }}
QLabel#stepFail {{ color: {DANGER}; }}
QLabel#metricValue {{ font-size: 18px; font-weight: 700; color: {ACCENT}; }}
QStatusBar {{ background-color: {BG_PANEL}; color: {TEXT_MUTED}; }}
"""


def apply_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    app.setStyleSheet(DARK_QSS)
    app.setFont(QFont("Segoe UI", 10))


def set_language_direction(app: QApplication, lang: str) -> None:
    """Arabic → RTL; anything else → LTR. Applied instantly on language
    change (Spec section 3: no restart needed)."""
    direction = Qt.RightToLeft if lang == "ar" else Qt.LeftToRight
    app.setLayoutDirection(direction)
