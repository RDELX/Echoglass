"""Background thread that translates transcripts in order, so ASR never waits on it.

Final lines are translated in order and feed the context. Live partials (sentences still
being spoken) are optional: only the newest one is kept, it's translated only when no final
line is waiting, and it never enters the context.
"""

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
                 on_result: Callable[[Translated], None], translate_partials: bool = False):
        self.translator = translator
        self.target = target
        self.on_result = on_result
        self._context: deque[ContextLine] = deque(maxlen=context_lines)
        self._q: "queue.Queue[Transcript | object]" = queue.Queue()
        self._thread: threading.Thread | None = None
        self.translate_partials = translate_partials
        self._partial: Transcript | None = None
        self._partial_lock = threading.Lock()
        self._last_final_uid = 0

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
        if t.final:
            self._last_final_uid = max(self._last_final_uid, t.uid)
            self._q.put(t)
        elif self.translate_partials and self.translator is not None:
            with self._partial_lock:
                self._partial = t

    def stop(self) -> None:
        if self._thread is not None:
            self._q.put(_STOP)
            self._thread.join()
            self._thread = None

    def _loop(self) -> None:
        while True:
            try:
                t = self._q.get(timeout=0.05)
            except queue.Empty:
                with self._partial_lock:
                    p, self._partial = self._partial, None
                if p is not None and p.uid > self._last_final_uid:
                    r = self._translate(p)
                    if p.uid > self._last_final_uid:  # still unfinished: worth showing
                        self.on_result(r)
                continue
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
        if out and t.final:
            self._context.append(ContextLine(t.text, out))
        return Translated(t, out, time.perf_counter() - t0)
