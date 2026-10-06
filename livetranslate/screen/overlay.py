"""Click-through window laid exactly over the chosen screen region, painting each
recognised line's translation on top of the original text."""

import ctypes
from dataclasses import dataclass

from PyQt6.QtCore import QRect, QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPen
from PyQt6.QtWidgets import QWidget

from ..ui import theme

WDA_EXCLUDEFROMCAPTURE = 0x11  # Windows 10 2004+: invisible to screen capture


@dataclass
class OverlayLine:
    rect: QRect          # in widget (logical) coordinates
    text: str            # translation to draw


class ScreenTextOverlay(QWidget):
    def __init__(self, opacity: float = 0.88, language: str | None = None):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.Tool | Qt.WindowType.WindowTransparentForInput)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.opacity = opacity
        self.language = language
        self.lines: list[OverlayLine] = []
        self.show_frame = True

    def showEvent(self, ev) -> None:
        super().showEvent(ev)
        # Our own translations must never be read back by the screen OCR.
        try:
            ctypes.windll.user32.SetWindowDisplayAffinity(int(self.winId()), WDA_EXCLUDEFROMCAPTURE)
        except Exception:
            pass

    def set_lines(self, lines: list[OverlayLine]) -> None:
        self.lines = lines
        self.update()

    def paintEvent(self, ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        if self.show_frame:
            p.setPen(QPen(QColor(theme.ACCENT), 1, Qt.PenStyle.DashLine))
            p.drawRect(self.rect().adjusted(0, 0, -1, -1))
        for line in self.lines:
            self._draw_line(p, line)

    def _draw_line(self, p: QPainter, line: OverlayLine) -> None:
        r = QRectF(line.rect).adjusted(-3, -2, 3, 2)
        # Fit the translation into the original line's box: start at the original text
        # height, shrink to 65% if needed, then let it run on to the region's right edge.
        px = max(9.0, r.height() * 0.78)
        font = theme.ui_font(10, QFont.Weight.Medium, language=self.language)
        avail = max(r.width(), self.width() - r.left() - 4)
        for _ in range(8):
            font.setPixelSize(int(px))
            if QFontMetricsF(font).horizontalAdvance(line.text) <= avail or px <= r.height() * 0.5:
                break
            px *= 0.92
        fm = QFontMetricsF(font)
        width = min(avail, max(r.width(), fm.horizontalAdvance(line.text) + 6))
        box = QRectF(r.left(), r.top(), width, r.height())
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(16, 17, 22, int(255 * self.opacity)))
        p.drawRoundedRect(box, 3, 3)
        p.setFont(font)
        p.setPen(QColor("#f2f3f7"))
        text = fm.elidedText(line.text, Qt.TextElideMode.ElideRight, box.width() - 4)
        p.drawText(box.adjusted(3, 0, -1, 0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, text)
