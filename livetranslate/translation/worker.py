"""Background thread that translates transcripts in order, so ASR never waits on it."""

import logging
import queue
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Callable

from ..asr import Transcript
from .base import ContextLine, Translator

log = logging.getLogger(__name__)

_STOP = object()


@dataclass
class Translated:
    transcript: Transcript
    translation: str | None    # None if translation failed or is disabled
    seconds: float = 0.0
    error: str | None = None


class TranslationWorker:
    def __init__(self, translator: Translator | None, target: str, context_lines: int,
                 on_result: Callable[[Translated], None]):
        self.translator = translator
        self.target = target
        self.on_result = on_result
        self._context: deque[ContextLine] = deque(maxlen=context_lines)
        self._q: "queue.Queue[Transcript | object]" = queue.Queue()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="translate", daemon=True)
        self._thread.start()

    def warmup(self) -> None:
        """Make the backend load its model now (Ollama's first request can take ~1 min)."""
        if self.translator is None:
            return
        t0 = time.perf_counter()
        try:
            self.translator.translate("Hello.", "en", self.target, [])
            log.info("Translator ready in %.1fs", time.perf_counter() - t0)
        except Exception as e:
            log.warning("Translator warmup failed: %s", e)

    def submit(self, t: Transcript) -> None:
        self._q.put(t)

    def stop(self) -> None:
        if self._thread is not None:
            self._q.put(_STOP)
            self._thread.join()
            self._thread = None

    def _loop(self) -> None:
        while True:
            t = self._q.get()
            if t is _STOP:
                return
            self.on_result(self._translate(t))

    def _translate(self, t: Transcript) -> Translated:
        if self.translator is None or t.language == self.target:
            return Translated(t, None)
        t0 = time.perf_counter()
        try:
            out = self.translator.translate(t.text, t.language, self.target, list(self._context))
        except Exception as e:
            log.warning("Translation failed: %s", e)
            return Translated(t, None, time.perf_counter() - t0, error=str(e))
        if out:
            self._context.append(ContextLine(t.text, out))
        return Translated(t, out, time.perf_counter() - t0)
