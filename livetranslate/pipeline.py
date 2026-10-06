"""Wires audio → (vocal separation) → VAD → ASR together on worker threads.

The pipeline only produces `Transcript`s through a callback; consumers (console,
translation, Qt UI) decide what to do with them.

Live captions: while someone is still talking, the segmenter's open utterance is
snapshotted every `live_interval_s` and transcribed quickly as a partial
(`Transcript.final=False`). Partials only run when no finished utterance is waiting, and
only the newest snapshot is kept, so they never delay final lines.
"""

import logging
import queue
import threading
import time
from typing import Callable

import numpy as np

from .asr import Segmenter, Transcriber, Transcript, Utterance
from .audio import LoopbackCapture
from .config import Config

log = logging.getLogger(__name__)

_STOP = object()


class Pipeline:
    def __init__(self, cfg: Config, on_transcript: Callable[[Transcript], None],
                 transcriber: Transcriber | None = None):
        self.cfg = cfg
        self.on_transcript = on_transcript
        self.transcriber = transcriber or Transcriber(cfg.asr)
        self.separator = None
        if cfg.music_mode:
            from .audio.separator import VocalSeparator
            self.separator = VocalSeparator()
            self.separator.warmup()
        self._audio_q: "queue.Queue[np.ndarray | object]" = queue.Queue()
        self._utt_q: "queue.Queue[Utterance | object]" = queue.Queue()
        self._capture: LoopbackCapture | None = None
        self._threads: list[threading.Thread] = []
        self._partial: Utterance | None = None   # newest snapshot of the open utterance
        self._partial_lock = threading.Lock()
        self._last_final_uid = 0

    def start(self) -> None:
        self.start_without_capture()
        self._capture = LoopbackCapture(self._audio_q, self.cfg.device_index)
        self._capture.start()

    @property
    def device_name(self) -> str:
        return self._capture.device_name if self._capture else ""

    def feed(self, audio: np.ndarray) -> None:
        """Push 16 kHz mono audio directly (file input / tests) instead of capturing."""
        self._audio_q.put(audio)

    def start_without_capture(self) -> None:
        self._threads = [
            threading.Thread(target=self._segment_loop, name="vad", daemon=True),
            threading.Thread(target=self._asr_loop, name="asr", daemon=True),
        ]
        for t in self._threads:
            t.start()

    def stop(self) -> None:
        """Stop capturing, finish transcribing what is already queued, then return."""
        if self._capture is not None:
            self._capture.stop()
            self._capture = None
        self._audio_q.put(_STOP)
        for t in self._threads:
            t.join()
        self._threads = []

    def _segment_loop(self) -> None:
        seg = Segmenter(self.cfg.vad)
        last_snapshot = 0.0
        while True:
            chunk = self._audio_q.get()
            if chunk is _STOP:
                if self.separator is not None:
                    for utt in seg.feed(self.separator.flush()):
                        self._utt_q.put(utt)
                tail = seg.flush()
                if tail is not None:
                    self._utt_q.put(tail)
                self._utt_q.put(_STOP)
                return
            if self.separator is not None:
                chunk = self.separator.feed(chunk)
            for utt in seg.feed(chunk):
                self._utt_q.put(utt)
            live = self.cfg.asr.live_captions
            if live and time.monotonic() - last_snapshot >= self.cfg.asr.live_interval_s:
                snap = seg.snapshot()
                if snap is not None:
                    last_snapshot = time.monotonic()
                    with self._partial_lock:
                        self._partial = snap

    def _asr_loop(self) -> None:
        while True:
            try:
                utt = self._utt_q.get(timeout=0.05)
            except queue.Empty:
                self._run_partial()
                continue
            if utt is _STOP:
                return
            self._last_final_uid = max(self._last_final_uid, utt.uid)
            try:
                result = self.transcriber.transcribe(utt.audio, utt.start, utt.uid, final=True)
            except Exception:
                log.exception("Transcription failed")
                continue
            if result is not None:
                self.on_transcript(result)

    def _run_partial(self) -> None:
        with self._partial_lock:
            snap, self._partial = self._partial, None
        if snap is None or snap.uid <= self._last_final_uid:
            return  # that sentence already finished
        try:
            result = self.transcriber.transcribe(snap.audio, snap.start, snap.uid, final=False)
        except Exception:
            log.exception("Partial transcription failed")
            return
        if result is not None and snap.uid > self._last_final_uid:
            self.on_transcript(result)
