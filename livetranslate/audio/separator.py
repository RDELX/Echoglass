"""Music mode: strip instruments with Demucs so VAD and Whisper only hear the voice.

Silero VAD scores singing over music as ~0 and Whisper mishears it, but both work on
the isolated vocal stem. Demucs is offline by design, so we stream it in short blocks
with some left context; each block costs ~0.1-0.2 s on an RTX 3090.
"""

import logging

import numpy as np
import soxr

log = logging.getLogger(__name__)

SAMPLE_RATE = 16000


class VocalSeparator:
    def __init__(self, block_s: float = 2.0, context_s: float = 3.0, device: str = "cuda"):
        import torch
        from demucs.pretrained import get_model

        self._torch = torch
        self.model = get_model("htdemucs").to(device).eval()
        self.device = device
        self.sr = self.model.samplerate
        self._vocals = self.model.sources.index("vocals")
        self.block = int(block_s * SAMPLE_RATE)
        self.context = int(context_s * SAMPLE_RATE)
        self._pending = np.zeros(0, dtype=np.float32)
        self._history = np.zeros(0, dtype=np.float32)
        log.info("Music mode: Demucs htdemucs loaded on %s", device)

    def _separate(self, x16: np.ndarray) -> np.ndarray:
        from demucs.apply import apply_model

        x = soxr.resample(x16, SAMPLE_RATE, self.sr).astype(np.float32)
        t = self._torch.from_numpy(np.stack([x, x]))[None].to(self.device)
        with self._torch.no_grad():
            out = apply_model(self.model, t, split=True, overlap=0.1, progress=False)
        v = out[0, self._vocals].mean(0).cpu().numpy()
        return soxr.resample(v, self.sr, SAMPLE_RATE).astype(np.float32)

    def _process_block(self, block: np.ndarray) -> np.ndarray:
        x = np.concatenate([self._history, block])
        vocals = self._separate(x)[-len(block):]
        self._history = x[-self.context:]
        return vocals

    def feed(self, chunk: np.ndarray) -> np.ndarray:
        """Returns separated vocals; output lags input by up to one block."""
        self._pending = np.concatenate([self._pending, chunk.astype(np.float32, copy=False)])
        out = []
        while len(self._pending) >= self.block:
            block, self._pending = self._pending[:self.block], self._pending[self.block:]
            out.append(self._process_block(block))
        return np.concatenate(out) if out else np.zeros(0, dtype=np.float32)

    def flush(self) -> np.ndarray:
        if not len(self._pending):
            return np.zeros(0, dtype=np.float32)
        block, self._pending = self._pending, np.zeros(0, dtype=np.float32)
        return self._process_block(block)

    def warmup(self) -> None:
        self._separate(np.zeros(SAMPLE_RATE * 2, dtype=np.float32))
