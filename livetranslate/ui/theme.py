"""Dark theme: colour tokens and the application stylesheet."""

from pathlib import Path

from PyQt6.QtGui import QColor, QFont, QPalette
from PyQt6.QtWidgets import QApplication

BG = "#0e1014"          # window
SURFACE = "#15181e"     # panels
SURFACE_2 = "#1c2028"   # controls
SURFACE_3 = "#252a34"   # hover
BORDER = "#262b35"
TEXT = "#e7e9ee"
TEXT_2 = "#b4bac6"      # translation secondary / labels
MUTED = "#7c8495"
ACCENT = "#8b9cff"      # periwinkle
ACCENT_DIM = "#2a2f52"
LIVE = "#3ddc97"
WARN = "#f5b74e"
ERROR = "#ff6b6b"

ASSETS = Path(__file__).parent / "assets"

# Windows fonts that cover Latin + Korean + Japanese + Chinese between them.
FONT_FAMILIES = ["Segoe UI Variable Text", "Segoe UI", "Yu Gothic UI", "Malgun Gothic",
                 "Microsoft YaHei UI"]
# CJK text looks wrong in another language's font (kana spacing, Han glyph shapes), so text
# in these languages puts its native font first.
_NATIVE_FONT = {"ja": "Yu Gothic UI", "ko": "Malgun Gothic", "zh": "Microsoft YaHei UI"}


def families_for(language: str | None) -> list[str]:
    native = _NATIVE_FONT.get(language or "")
    return [native] + [f for f in FONT_FAMILIES if f != native] if native else FONT_FAMILIES


def ui_font(point_size: float = 10, weight: QFont.Weight = QFont.Weight.Normal,
            language: str | None = None) -> QFont:
    f = QFont()
    f.setFamilies(families_for(language))
    f.setPointSizeF(point_size)
    f.setWeight(weight)
    return f


STYLESHEET = f"""
* {{ color: {TEXT}; }}
QMainWindow, #root {{ background: {BG}; }}
QToolTip {{ background: {SURFACE_2}; color: {TEXT}; border: 1px solid {BORDER}; padding: 4px 6px; }}

/* ---- top bar ---- */
#appName {{ font-size: 13pt; font-weight: 600; }}
#appName[live="true"] {{ color: {TEXT}; }}
QLabel#arrow {{ color: {MUTED}; font-size: 12pt; padding: 0 2px; }}
QLabel#fieldLabel {{ color: {MUTED}; font-size: 8.5pt; }}

QComboBox {{
    background: {SURFACE_2}; border: 1px solid {BORDER}; border-radius: 8px;
    padding: 5px 28px 5px 10px; min-height: 20px;
}}
QComboBox:hover {{ background: {SURFACE_3}; }}
QComboBox:focus {{ border-color: {ACCENT}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox::down-arrow {{ image: url({(ASSETS / "chevron-down.svg").as_posix()});
    width: 12px; height: 12px; margin-right: 10px; }}
QComboBox QAbstractItemView {{
    background: {SURFACE_2}; border: 1px solid {BORDER}; border-radius: 8px; padding: 4px;
    selection-background-color: {ACCENT_DIM}; selection-color: {TEXT}; outline: none;
}}

QPushButton {{
    background: {SURFACE_2}; border: 1px solid {BORDER}; border-radius: 8px;
    padding: 6px 12px;
}}
QPushButton:hover {{ background: {SURFACE_3}; }}
QPushButton:disabled {{ color: {MUTED}; }}

/* pill toggles (music mode) */
QPushButton#pill {{ border-radius: 15px; padding: 6px 14px; }}
QPushButton#pill:checked {{ background: {ACCENT_DIM}; border-color: {ACCENT}; color: #dfe3ff; }}

/* segmented control */
#segment {{ background: {SURFACE_2}; border: 1px solid {BORDER}; border-radius: 9px; }}
#segment QPushButton {{ background: transparent; border: none; border-radius: 7px;
    padding: 5px 12px; color: {MUTED}; }}
#segment QPushButton:hover {{ color: {TEXT}; }}
#segment QPushButton:checked {{ background: {SURFACE_3}; color: {TEXT}; }}

/* ghost icon-ish buttons in panel headers */
QPushButton#ghost {{ background: transparent; border: 1px solid transparent; color: {MUTED};
    padding: 3px 9px; border-radius: 6px; font-size: 9pt; }}
QPushButton#ghost:hover {{ background: {SURFACE_2}; color: {TEXT}; border-color: {BORDER}; }}

/* ---- transcript area ---- */
#panelHeader {{ background: {SURFACE}; border-bottom: 1px solid {BORDER}; }}
#panelTitle {{ color: {MUTED}; font-size: 9pt; font-weight: 600; letter-spacing: 0.5px; }}
#langChip {{ color: {ACCENT}; background: {ACCENT_DIM}; border-radius: 8px; padding: 1px 8px;
    font-size: 8.5pt; }}
#transcriptFrame {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 12px; }}
QScrollArea, #rows {{ background: transparent; border: none; }}
QTextBrowser {{ background: transparent; border: none; selection-background-color: {ACCENT_DIM}; }}
#divider {{ background: {BORDER}; }}

#rowTime {{ color: {MUTED}; font-size: 8pt; }}
#rowOriginal {{ color: {TEXT}; }}
#rowTranslation {{ color: {TEXT}; }}
#rowTranslation[pending="true"] {{ color: {MUTED}; font-style: italic; }}
#rowTranslation[failed="true"] {{ color: {ERROR}; }}
#rowRomaji {{ color: {TEXT_2}; }}
#rowOriginal[live="true"], #rowTranslation[live="true"], #rowRomaji[live="true"] {{ color: {TEXT_2}; font-style: italic; }}

#emptyTitle {{ font-size: 13pt; font-weight: 600; color: {TEXT_2}; }}
#emptyHint {{ color: {MUTED}; }}

QPushButton#jump {{ background: {ACCENT}; color: #10132a; border: none; border-radius: 14px;
    padding: 5px 14px; font-weight: 600; }}
QPushButton#jump:hover {{ background: #a3b1ff; }}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 4px 2px; }}
QScrollBar::handle:vertical {{ background: {SURFACE_3}; border-radius: 3px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: #343a47; }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{
    background: none; height: 0; }}

/* ---- bottom bar ---- */
#statusText {{ color: {TEXT_2}; }}
#statusText[kind="error"] {{ color: {ERROR}; }}
#statsText {{ color: {MUTED}; font-size: 9pt; }}

QPushButton#primary {{
    background: {ACCENT}; color: #10132a; border: none; border-radius: 12px;
    padding: 10px 26px; font-size: 11pt; font-weight: 600; min-width: 120px;
}}
QPushButton#primary:hover {{ background: #a3b1ff; }}
QPushButton#primary[running="true"] {{ background: {SURFACE_2}; color: {TEXT};
    border: 1px solid {BORDER}; }}
QPushButton#primary[running="true"]:hover {{ background: #3a2226; border-color: {ERROR};
    color: #ffd6d6; }}
QPushButton#primary:disabled {{ background: {SURFACE_2}; color: {MUTED}; }}
"""


def apply(app: QApplication) -> None:
    app.setStyle("Fusion")
    app.setFont(ui_font(10))
    pal = QPalette()
    for role, color in [
        (QPalette.ColorRole.Window, BG), (QPalette.ColorRole.Base, SURFACE),
        (QPalette.ColorRole.AlternateBase, SURFACE_2), (QPalette.ColorRole.Text, TEXT),
        (QPalette.ColorRole.WindowText, TEXT), (QPalette.ColorRole.Button, SURFACE_2),
        (QPalette.ColorRole.ButtonText, TEXT), (QPalette.ColorRole.Highlight, ACCENT_DIM),
        (QPalette.ColorRole.HighlightedText, TEXT), (QPalette.ColorRole.PlaceholderText, MUTED),
    ]:
        pal.setColor(role, QColor(color))
    app.setPalette(pal)
    app.setStyleSheet(STYLESHEET)
