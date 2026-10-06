"""Silero-VAD-driven segmenter: turns a stream of 16 kHz audio into whole utterances."""

from collections import deque
from dataclasses import dataclass

import numpy as np
from pysilero_vad import SileroVoiceActivityDetector

from ..config import VadConfig

SAMPLE_RATE = 16000
FRAME = SileroVoiceActivityDetector.chunk_samples()  # 512 samples = 32 ms
FRAME_MS = FRAME * 1000 // SAMPLE_RATE


@dataclass
class Utterance:
    audio: np.ndarray  # 16 kHz mono float32
    start: float       # seconds since the segmenter started


class Segmenter:
    """Feed arbitrary-length chunks with `feed()`; it returns any utterances completed.

    An utterance opens when speech probability crosses `threshold` and closes after
    `min_silence_ms` of frames below `neg_threshold`. Long monologues are cut at the
    first dip in speech after `soft_max_s`, and unconditionally at `hard_max_s`.
    """

    def __init__(self, cfg: VadConfig):
        self.cfg = cfg
        self.vad = SileroVoiceActivityDetector()
        self._pending = np.zeros(0, dtype=np.float32)
        self._pre_roll: deque[np.ndarray] = deque(maxlen=max(1, cfg.pre_roll_ms // FRAME_MS))
        self._frames: list[np.ndarray] = []
        self._speech_frames = 0
        self._silence_frames = 0
        self._in_speech = False
        self._utt_start_frame = 0
        self._frame_index = 0

    def feed(self, chunk: np.ndarray) -> list[Utterance]:
        self._pending = np.concatenate([self._pending, chunk.astype(np.float32, copy=False)])
        done: list[Utterance] = []
        n = len(self._pending) // FRAME
        for i in range(n):
            frame = self._pending[i * FRAME:(i + 1) * FRAME]
            utt = self._process_frame(frame)
            if utt is not None:
                done.append(utt)
        self._pending = self._pending[n * FRAME:]
        return done

    def flush(self) -> Utterance | None:
        """Close any open utterance (e.g. on Stop)."""
        return self._close() if self._in_speech else None

    def _process_frame(self, frame: np.ndarray) -> Utterance | None:
        prob = self.vad.process_samples(frame.tolist())
        self._frame_index += 1
        cfg = self.cfg

        if not self._in_speech:
            self._pre_roll.append(frame)
            if prob >= cfg.threshold:
                self._in_speech = True
                self._frames = list(self._pre_roll)
                self._pre_roll.clear()
                self._utt_start_frame = self._frame_index - len(self._frames)
                self._speech_frames = 1
                self._silence_frames = 0
            return None

        self._frames.append(frame)
        if prob >= cfg.threshold:
            self._speech_frames += 1
            self._silence_frames = 0
        elif prob < cfg.neg_threshold:
            self._silence_frames += 1

        length_s = len(self._frames) * FRAME / SAMPLE_RATE
        if self._silence_frames * FRAME_MS >= cfg.min_silence_ms:
            return self._close()
        if length_s >= cfg.hard_max_s:
            return self._close()
        if length_s >= cfg.soft_max_s and prob < cfg.threshold:
            return self._close()
        return None

    def _close(self) -> Utterance | None:
        frames, speech = self._frames, self._speech_frames
        start = self._utt_start_frame * FRAME / SAMPLE_RATE
        self._frames = []
        self._in_speech = False
        self._speech_frames = 0
        self._silence_frames = 0
        if speech * FRAME_MS < self.cfg.min_speech_ms:
            return None
        return Utterance(audio=np.concatenate(frames), start=start)
