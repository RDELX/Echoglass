"""Full-screen dimmed layer where the user drags a rectangle around the text to translate."""

from PyQt6.QtCore import QEventLoop, QPoint, QRect, Qt
from PyQt6.QtGui import QColor, QFont, QGuiApplication, QPainter, QPen
from PyQt6.QtWidgets import QWidget

from ..ui import theme


class RegionPicker(QWidget):
    def __init__(self):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setCursor(Qt.CursorShape.CrossCursor)
        screen = QGuiApplication.screenAt(QGuiApplication.primaryScreen().geometry().center())
        self.setGeometry(screen.virtualGeometry())
        self._start: QPoint | None = None
        self._end: QPoint | None = None
        self.result: QRect | None = None
        self._loop = QEventLoop()

    @classmethod
    def pick(cls) -> QRect | None:
        """Blocks (with a local event loop) until the user drags a box or presses Esc.
        Returns the box in global screen coordinates."""
        p = cls()
        p.show()
        p.activateWindow()
        p.raise_()
        p._loop.exec()
        return p.result

    def _rect(self) -> QRect:
        return QRect(self._start, self._end).normalized() if self._start and self._end else QRect()

    def paintEvent(self, ev) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(0, 0, 0, 110))
        r = self._rect()
        if not r.isNull():
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
            p.fillRect(r, Qt.GlobalColor.transparent)
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
            p.setPen(QPen(QColor(theme.ACCENT), 2))
            p.drawRect(r)
        p.setPen(QColor("#ffffff"))
        f = QFont(theme.FONT_FAMILIES[0]); f.setPointSize(13); p.setFont(f)
        p.drawText(self.rect().adjusted(0, 40, 0, 0), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                   "Drag a box around the text to translate (e.g. the live chat).  Esc to cancel.")

    def mousePressEvent(self, ev) -> None:
        self._start = self._end = ev.position().toPoint()
        self.update()

    def mouseMoveEvent(self, ev) -> None:
        if self._start is not None:
            self._end = ev.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, ev) -> None:
        r = self._rect()
        if r.width() > 20 and r.height() > 20:
            self.result = r.translated(self.geometry().topLeft())
        self._finish()

    def keyPressEvent(self, ev) -> None:
        if ev.key() == Qt.Key.Key_Escape:
            self._finish()

    def _finish(self) -> None:
        self.close()
        self._loop.quit()
