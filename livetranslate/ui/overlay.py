"""Transparent always-on-top subtitle window to put over (fullscreen) video.

Unlocked: shows a frame you can drag and resize. Locked: mouse clicks pass straight
through to the video underneath; unlock it from the main window.
"""

from PyQt6.QtCore import QPoint, QRect, Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QGuiApplication, QPainter, QPen
from PyQt6.QtWidgets import (QGraphicsDropShadowEffect, QLabel, QSizeGrip, QVBoxLayout,
                             QWidget)

from ..config import OverlayConfig
from . import theme
from .transcript_view import Entry


class SubtitleOverlay(QWidget):
    def __init__(self, cfg: OverlayConfig):
        super().__init__(None)
        self.cfg = cfg
        self._entries: list[Entry] = []
        self._target_lang: str | None = None
        self._drag_from: QPoint | None = None
        self._faded = True

        self.setWindowTitle("LiveTranslate subtitles")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self._apply_flags()

        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 14, 24, 14)
        lay.setSpacing(4)
        self.hint = QLabel("Drag to move · resize from the corner · lock it from the main window "
                           "so clicks go through to the video")
        self.hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hint.setStyleSheet(f"color: {theme.MUTED}; font-size: 9pt;")
        self.hint.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        lay.addWidget(self.hint)
        lay.addStretch(1)
        self._labels: list[tuple[QLabel, QLabel]] = []
        for _ in range(4):
            orig, trans = QLabel(), QLabel()
            for lbl in (orig, trans):
                lbl.setWordWrap(True)
                lbl.setAlignment(Qt.AlignmentFlag.AlignHCenter)
                lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
                shadow = QGraphicsDropShadowEffect(lbl)
                shadow.setBlurRadius(8)
                shadow.setOffset(0, 1)
                shadow.setColor(QColor(0, 0, 0, 230))
                lbl.setGraphicsEffect(shadow)
            orig.setStyleSheet("color: rgba(230,232,238,0.78);")
            trans.setStyleSheet("color: #ffffff;")
            lay.addWidget(orig)
            lay.addWidget(trans)
            self._labels.append((orig, trans))

        self.grip = QSizeGrip(self)
        self.grip.resize(18, 18)

        self._fade_timer = QTimer(self, singleShot=True, timeout=self._fade)
        # Some players re-assert their own z-order; keep ourselves on top.
        self._raise_timer = QTimer(self, interval=3000, timeout=self._keep_on_top)

        self._restore_geometry()
        self.apply_config()

    # ---- configuration ---------------------------------------------------------------

    def _apply_flags(self) -> None:
        flags = (Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                 | Qt.WindowType.Tool)
        if self.cfg.locked:
            flags |= Qt.WindowType.WindowTransparentForInput
        self.setWindowFlags(flags)

    def apply_config(self) -> None:
        for i, (orig, trans) in enumerate(self._labels):
            orig.setFont(theme.ui_font(self.cfg.font_size * 0.62))
            trans.setFont(theme.ui_font(self.cfg.font_size, QFont.Weight.DemiBold,
                                        language=self._target_lang))
        self.hint.setVisible(not self.cfg.locked)
        self.grip.setVisible(not self.cfg.locked)
        self._render()
        self.update()

    def set_locked(self, locked: bool) -> None:
        self.cfg.locked = locked
        visible = self.isVisible()
        self._apply_flags()          # changing window flags hides the window
        self.apply_config()
        if visible:
            self.show()

    def set_target_language(self, code: str) -> None:
        self._target_lang = code
        self.apply_config()

    # ---- content ---------------------------------------------------------------------

    def show_entries(self, entries: list[Entry]) -> None:
        self._entries = entries[-self.cfg.lines:]
        self._faded = False
        self._render()
        self._fade_timer.start(int(self.cfg.hide_after_s * 1000))

    def clear(self) -> None:
        self._entries = []
        self._render()

    def _fade(self) -> None:
        self._faded = True
        self._render()

    def _render(self) -> None:
        shown = [] if self._faded else self._entries
        pad = len(self._labels) - len(shown)
        for i, (orig, trans) in enumerate(self._labels):
            e = shown[i - pad] if i >= pad else None
            if e is None:
                orig.hide(); trans.hide()
                continue
            orig.setFont(theme.ui_font(self.cfg.font_size * 0.62, language=e.language))
            orig.setText(e.text)
            orig.setVisible(self.cfg.show_original and e.state not in ("same", "off"))
            if e.state == "done":
                trans.setText(e.translation)
            elif e.state in ("same", "off"):
                trans.setText(e.text)
            else:
                trans.setText("…")
            trans.show()
        self.update()

    # ---- painting --------------------------------------------------------------------

    def paintEvent(self, ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        visible = [w for pair in self._labels for w in pair if w.isVisible()]
        if visible:
            box = QRect()
            for w in visible:
                box = box.united(w.geometry())
            box = box.adjusted(-18, -10, 18, 10).intersected(self.rect())
            # shrink to the text width so the backdrop hugs the subtitles
            text_w = max(w.fontMetrics().boundingRect(
                QRect(0, 0, w.width(), 10000), Qt.TextFlag.TextWordWrap, w.text()).width()
                for w in visible)
            cx = box.center().x()
            box.setLeft(max(0, cx - text_w // 2 - 22))
            box.setRight(min(self.width(), cx + text_w // 2 + 22))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(8, 9, 12, int(255 * self.cfg.background_opacity)))
            p.drawRoundedRect(box, 12, 12)
        if not self.cfg.locked:
            p.setPen(QPen(QColor(theme.ACCENT), 1.5, Qt.PenStyle.DashLine))
            p.setBrush(QColor(20, 22, 30, 60))
            p.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 12, 12)

    def resizeEvent(self, ev) -> None:
        self.grip.move(self.width() - self.grip.width() - 4, self.height() - self.grip.height() - 4)
        super().resizeEvent(ev)

    # ---- dragging --------------------------------------------------------------------

    def mousePressEvent(self, ev) -> None:
        if ev.button() == Qt.MouseButton.LeftButton:
            self._drag_from = ev.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, ev) -> None:
        if self._drag_from is not None:
            self.move(ev.globalPosition().toPoint() - self._drag_from)

    def mouseReleaseEvent(self, ev) -> None:
        self._drag_from = None
        self.save_geometry()

    # ---- placement -------------------------------------------------------------------

    def _restore_geometry(self) -> None:
        g = self.cfg.geometry
        screens = QGuiApplication.screens()
        if g and any(s.availableGeometry().intersects(QRect(*g)) for s in screens):
            self.setGeometry(QRect(*g))
            return
        scr = QGuiApplication.primaryScreen().geometry()
        w, h = int(scr.width() * 0.7), 300
        self.setGeometry(scr.x() + (scr.width() - w) // 2, scr.y() + scr.height() - h - 70, w, h)

    def save_geometry(self) -> None:
        g = self.geometry()
        self.cfg.geometry = [g.x(), g.y(), g.width(), g.height()]

    def showEvent(self, ev) -> None:
        self._raise_timer.start()
        super().showEvent(ev)

    def hideEvent(self, ev) -> None:
        self._raise_timer.stop()
        self.save_geometry()
        super().hideEvent(ev)

    def _keep_on_top(self) -> None:
        if self.isVisible():
            self.raise_()
