"""Transparent always-on-top subtitle window to put over (fullscreen) video.

Unlocked: shows a frame you can drag and resize. Locked: mouse clicks pass straight
through to the video underneath; unlock it from the main window.

Rolling captions: the sentence still being spoken is shown live (dimmed) at the bottom and
grows as it's recognised; when lines are added the text block slides up smoothly.
"""

import html

from PyQt6.QtCore import QEasingCurve, QPoint, QPropertyAnimation, QRect, Qt, QTimer
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
        self._live: Entry | None = None
        self._target_lang: str | None = None
        self._drag_from: QPoint | None = None
        self._faded = True

        self.setWindowTitle("Echoglass subtitles")
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

        # Subtitle block: positioned by hand (anchored to the bottom) so it can slide.
        self._body = QWidget(self)
        self._body.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        body_lay = QVBoxLayout(self._body)
        body_lay.setContentsMargins(0, 0, 0, 0)
        body_lay.setSpacing(4)
        self._slide = QPropertyAnimation(self._body, b"pos", self)
        self._slide.setDuration(220)
        self._slide.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._slide.valueChanged.connect(lambda _: self.update())
        self._labels: list[tuple[QLabel, QLabel]] = []
        for _ in range(5):  # up to 4 finished lines + the live one
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
            body_lay.addWidget(orig)
            body_lay.addWidget(trans)
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

    def show_entries(self, entries: list[Entry], live: Entry | None = None) -> None:
        keep = self.cfg.lines - 1 if live is not None else self.cfg.lines
        self._entries = entries[-max(keep, 1):] if keep > 0 else []
        self._live = live
        self._faded = False
        self._render(animate=True)
        self._fade_timer.start(int(self.cfg.hide_after_s * 1000))

    def clear(self) -> None:
        self._entries = []
        self._live = None
        self._render()

    def _fade(self) -> None:
        self._faded = True
        self._render()

    def _render(self, animate: bool = False) -> None:
        shown = [] if self._faded else list(self._entries)
        if self._live is not None and not self._faded:
            shown.append(self._live)
        pad = len(self._labels) - len(shown)
        for i, (orig, trans) in enumerate(self._labels):
            e = shown[i - pad] if i >= pad else None
            if e is None:
                orig.hide(); trans.hide()
                continue
            live = e is self._live
            orig.setFont(theme.ui_font(self.cfg.font_size * 0.62, language=e.language))
            if e.romaji:  # small romaji line under the Japanese
                orig.setTextFormat(Qt.TextFormat.RichText)
                orig.setText(f"{html.escape(e.text)}<br><span style='font-size:80%'>"
                             f"{html.escape(e.romaji)}</span>")
            else:
                orig.setTextFormat(Qt.TextFormat.PlainText)
                orig.setText(e.text)
            orig.setVisible(self.cfg.show_original and e.state not in ("same", "off"))
            if e.state == "done":
                trans.setText(e.translation)
            elif e.state in ("same", "off"):
                trans.setText(e.text)
            else:
                trans.setText("…")
            trans.setStyleSheet("color: rgba(255,255,255,0.72);" if live else "color: #ffffff;")
            trans.show()
        self._place_body(animate)
        self.update()

    def _place_body(self, animate: bool) -> None:
        old_h = self._body.height()
        w = max(100, self.width() - 48)
        self._body.setFixedWidth(w)
        h = self._body.layout().totalHeightForWidth(w)
        self._body.setFixedHeight(max(h, 0))
        target = QPoint(24, self.height() - h - 14)
        if animate and self.isVisible() and h > old_h and old_h > 0:
            # New text appeared below: start where the old block was and slide up.
            self._slide.stop()
            self._slide.setStartValue(QPoint(24, target.y() + (h - old_h)))
            self._slide.setEndValue(target)
            self._slide.start()
        elif self._slide.state() != QPropertyAnimation.State.Running:
            self._body.move(target)
        else:
            self._slide.setEndValue(target)

    # ---- painting --------------------------------------------------------------------

    def paintEvent(self, ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        visible = [w for pair in self._labels for w in pair if w.isVisible()]
        if visible:
            box = QRect()
            off = self._body.pos()
            for w in visible:
                box = box.united(w.geometry().translated(off))
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
        self._place_body(animate=False)

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
