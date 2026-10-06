"""Screen text translation loop: capture region → OCR → translate new lines → overlay.

Capture happens on the UI thread (Qt screen grab, ~10 ms) every `interval_ms`; OCR and
translation run on their own threads. Translations are cached by normalised line text,
so lines that just scroll up aren't translated again. Lines already in the target
language are left alone (no box drawn over them).
"""

import logging
import queue
import re
import threading
from collections import OrderedDict

import numpy as np
from PyQt6.QtCore import QObject, QRect, QTimer, pyqtSignal
from PyQt6.QtGui import QGuiApplication, QImage

from ..config import Config
from ..translation import create_translator
from .overlay import OverlayLine, ScreenTextOverlay

log = logging.getLogger(__name__)

_SKIP = object()  # cache value: line needs no translation
_NORM = re.compile(r"\s+")


def _key(text: str) -> str:
    return _NORM.sub("", text).lower()


class ScreenTranslator(QObject):
    status = pyqtSignal(str, str)       # message, kind (same kinds as the engine)
    _ocr_done = pyqtSignal(object)      # (lines, dpr)
    _translated = pyqtSignal()

    def __init__(self, cfg: Config):
        super().__init__()
        self.cfg = cfg
        self.region: QRect | None = None
        self.overlay: ScreenTextOverlay | None = None
        self._ocr = None
        self._ocr_busy = False
        self._lines: list = []
        self._dpr = 1.0
        self._cache: OrderedDict[str, object] = OrderedDict()
        self._todo: "queue.Queue[str]" = queue.Queue()
        self._pending: set[str] = set()
        self._texts: dict[str, str] = {}
        self._translator = None
        self._translator_key = None
        self._timer = QTimer(self, timeout=self._tick)
        self._ocr_done.connect(self._on_ocr)
        self._translated.connect(self._refresh)
        threading.Thread(target=self._translate_loop, name="screen-translate", daemon=True).start()

    @property
    def running(self) -> bool:
        return self._timer.isActive()

    # ---- lifecycle -------------------------------------------------------------------

    def start(self, region: QRect) -> None:
        self.region = region
        if self.overlay is None:
            self.overlay = ScreenTextOverlay(self.cfg.screen.opacity, self.cfg.translation.target_language)
        self.overlay.setGeometry(region)
        self.overlay.show_frame = True
        self.overlay.show()
        QTimer.singleShot(2500, self._hide_frame)
        self._timer.start(self.cfg.screen.interval_ms)
        self.status.emit("Translating screen text", "live")
        self._tick()

    def _hide_frame(self) -> None:
        if self.overlay is not None:
            self.overlay.show_frame = False
            self.overlay.update()

    def stop(self) -> None:
        self._timer.stop()
        if self.overlay is not None:
            self.overlay.hide()
            self.overlay.set_lines([])
        self._lines = []

    def set_target_language(self, code: str) -> None:
        self._cache.clear()
        if self.overlay is not None:
            self.overlay.language = code
            self.overlay.set_lines([])

    # ---- capture + OCR ---------------------------------------------------------------

    def _tick(self) -> None:
        if self._ocr_busy or self.region is None:
            return
        r = self.region
        screen = QGuiApplication.screenAt(r.center()) or QGuiApplication.primaryScreen()
        g = screen.geometry()
        pix = screen.grabWindow(0, r.x() - g.x(), r.y() - g.y(), r.width(), r.height())
        img = pix.toImage().convertToFormat(QImage.Format.Format_RGB888)
        w, h, bpl = img.width(), img.height(), img.bytesPerLine()
        arr = np.frombuffer(img.constBits().asstring(bpl * h), np.uint8).reshape(h, bpl)[:, :w * 3]
        bgr = arr.reshape(h, w, 3)[:, :, ::-1].copy()
        self._ocr_busy = True
        threading.Thread(target=self._run_ocr, args=(bgr, pix.devicePixelRatio()), daemon=True).start()

    def _run_ocr(self, bgr, dpr: float) -> None:
        try:
            if self._ocr is None:
                from .ocr import ScreenOCR
                self._ocr = ScreenOCR()
            lines = self._ocr.read(bgr)
        except Exception as e:
            log.exception("Screen OCR failed")
            self.status.emit(f"Screen text: OCR failed ({e})", "error")
            lines = []
        self._ocr_done.emit((lines, dpr))

    def _on_ocr(self, payload) -> None:
        self._ocr_busy = False
        self._lines, self._dpr = payload
        # Newest lines (bottom of a chat) first.
        for line in reversed(self._lines):
            k = _key(line.text)
            if k and k not in self._cache and k not in self._pending:
                self._pending.add(k)
                self._texts[k] = line.text
                self._todo.put(k)
        self._refresh()

    def _refresh(self) -> None:
        if self.overlay is None or not self.running:
            return
        out = []
        for line in self._lines:
            t = self._cache.get(_key(line.text))
            if t is None or t is _SKIP:
                continue
            d = self._dpr
            out.append(OverlayLine(QRect(int(line.x / d), int(line.y / d), int(line.w / d), int(line.h / d)), t))
        self.overlay.set_lines(out)

    # ---- translation -----------------------------------------------------------------

    def _needs_translation(self, text: str, target: str) -> bool:
        letters = [c for c in text if c.isalpha()]
        if not letters:
            return False  # numbers, emotes, punctuation
        if target == "en" and all(ord(c) < 0x250 for c in letters):
            return False  # already Latin script: assume it's English (saves a request)
        return True

    def _get_translator(self):
        tc = self.cfg.translation
        key = (tc.backend, tc.ollama_model, tc.lmstudio_model, tc.claude_model, tc.openai_model)
        if key != self._translator_key:
            self._translator = create_translator(tc)
            self._translator_key = key
        return self._translator

    def _translate_loop(self) -> None:
        while True:
            k = self._todo.get()
            text = self._texts.get(k, "")
            target = self.cfg.translation.target_language
            result: object = _SKIP
            try:
                if self._needs_translation(text, target):
                    tr = self._get_translator()
                    if tr is not None:
                        out = tr.translate(text, None, target, [], kind="text").strip()
                        if out and _key(out) != k:
                            result = out
            except Exception as e:
                log.warning("Screen text translation failed: %s", e)
                self.status.emit(f"Screen text: translation failed ({e})", "error")
                self._pending.discard(k)
                continue
            self._cache[k] = result
            while len(self._cache) > 3000:
                self._cache.popitem(last=False)
            self._pending.discard(k)
            self._translated.emit()
