"""Runs the audio → ASR → translation pipeline for the UI, off the UI thread.

Everything slow (loading Whisper, Demucs, the translator; stopping capture) happens on
plain Python threads. Results come back as Qt signals, which Qt delivers on the UI thread.
"""

import itertools
import logging
import threading

from PyQt6.QtCore import QObject, pyqtSignal

from ..asr import Transcriber, Transcript
from ..config import Config
from ..pipeline import Pipeline
from ..translation import Translated, TranslationWorker, create_translator

log = logging.getLogger(__name__)


class Engine(QObject):
    status = pyqtSignal(str, str)          # message, kind: idle | busy | live | error
    running_changed = pyqtSignal(bool)
    original = pyqtSignal(int, object)      # entry id, Transcript
    translated = pyqtSignal(int, object)    # entry id, Translated

    def __init__(self, cfg: Config):
        super().__init__()
        self.cfg = cfg
        self.running = False
        self.busy = False
        self._transcriber: Transcriber | None = None
        self._pipeline: Pipeline | None = None
        self._worker: TranslationWorker | None = None
        self._ids = itertools.count(1)
        self._entry_of: dict[int, int] = {}   # id(Transcript) -> entry id
        self._lock = threading.Lock()

    # ---- lifecycle -------------------------------------------------------------------

    def start(self) -> None:
        self._run_async(self._start)

    def stop(self) -> None:
        self._run_async(self._stop)

    def restart(self) -> None:
        self._run_async(lambda: (self._stop(), self._start()))

    def shutdown(self) -> None:
        """Blocking stop, for app exit."""
        with self._lock:
            self._stop(quiet=True)

    def _run_async(self, fn) -> None:
        def run():
            with self._lock:
                self.busy = True
                try:
                    fn()
                finally:
                    self.busy = False
        threading.Thread(target=run, daemon=True).start()

    def _start(self) -> None:
        if self.running:
            return
        try:
            self.cfg.sync_music_mode()
            if self._transcriber is None or self._transcriber.cfg.model != self.cfg.asr.model:
                self.status.emit("Loading speech recognition model…", "busy")

                def progress(done: float, total: float) -> None:
                    self.status.emit(f"Downloading speech model (first run only)… "
                                     f"{done / 1e9:.1f} / {total / 1e9:.1f} GB", "busy")
                self._transcriber = Transcriber(self.cfg.asr, on_download=progress)
                self._transcriber.warmup()
            self._transcriber.cfg = self.cfg.asr

            translator = None
            if self.cfg.translation.backend != "none":
                self.status.emit("Starting translator…", "busy")
                translator = create_translator(self.cfg.translation)
            tc = self.cfg.translation
            self._worker = TranslationWorker(translator, tc.target_language, tc.context_lines,
                                             self._on_translated)
            self._worker.start()
            self._worker.warmup()

            if self.cfg.music_mode:
                self.status.emit("Loading music mode…", "busy")
            self._pipeline = Pipeline(self.cfg, self._on_transcript, transcriber=self._transcriber)
            self._pipeline.start()
        except Exception as e:
            log.exception("Start failed")
            self._stop(quiet=True)
            self.status.emit(f"Couldn't start: {e}", "error")
            return
        self.running = True
        self.running_changed.emit(True)
        self.status.emit(f"Listening to {self._pipeline.device_name.replace(' [Loopback]', '')}",
                         "live")

    def _stop(self, quiet: bool = False) -> None:
        if self._pipeline is not None:
            if not quiet:
                self.status.emit("Finishing the last line…", "busy")
            self._pipeline.stop()
            self._pipeline = None
        if self._worker is not None:
            self._worker.stop()
            self._worker = None
        if self.running:
            self.running = False
            self.running_changed.emit(False)
        if not quiet:
            self.status.emit("Stopped", "idle")

    # ---- live setting changes --------------------------------------------------------

    def set_source_language(self, code: str | None) -> None:
        self.cfg.asr.language = code
        if self._transcriber is not None:
            self._transcriber.cfg = self.cfg.asr
            self._transcriber._sticky_language = None

    def set_target_language(self, code: str) -> None:
        self.cfg.translation.target_language = code
        if self._worker is not None:
            self._worker.target = code
            self._worker._context.clear()

    def set_backend(self, backend: str) -> None:
        self.cfg.translation.backend = backend
        if self._worker is None:
            return

        def swap():
            try:
                t = None if backend == "none" else create_translator(self.cfg.translation)
            except Exception as e:
                self.status.emit(f"Translator unavailable: {e}", "error")
                return
            if self._worker is not None:
                self._worker.translator = t
                self._worker._context.clear()
                self._worker.warmup()
                self.status.emit(f"Translating with {t.label}" if t else "Translation off", "live")
        threading.Thread(target=swap, daemon=True).start()

    # ---- pipeline callbacks (worker threads) -----------------------------------------

    def _on_transcript(self, t: Transcript) -> None:
        entry = next(self._ids)
        self._entry_of[id(t)] = entry
        self.original.emit(entry, t)
        if self._worker is not None:
            self._worker.submit(t)

    def _on_translated(self, r: Translated) -> None:
        entry = self._entry_of.pop(id(r.transcript), None)
        if entry is not None:
            self.translated.emit(entry, r)
