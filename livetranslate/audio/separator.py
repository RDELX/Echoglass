"""Music mode: strip instruments so VAD and Whisper only hear the voice.

Silero VAD scores singing over music as ~0 and Whisper mishears it, but both work on the
isolated vocal stem. We use Kim's Mel-Band RoFormer (MIT, HF KimberleyJSN/melbandroformer)
on the *original* stereo audio at 44.1 kHz: on 15 Japanese songs that cut the error rate
from 41.6% (htdemucs on 16 kHz mono, the old path) to 22.3% at the same per-block speed.

It's streamed in 2 s blocks with 3 s of left context (~0.12 s of GPU time per block on an
RTX 3090, 1.5 GB VRAM). Input is either the capture's native-rate stereo (`RawAudio`) or
16 kHz mono (file input/tests); output is 16 kHz mono vocals.
"""

import hashlib
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np
import soxr

log = logging.getLogger(__name__)

SAMPLE_RATE = 16000       # output (what VAD/ASR want)
MODEL_SR = 44100          # what the separator was trained on

# Pinned weights, verified by SHA-256 after download (never shipped with the app).
REPO = "KimberleyJSN/melbandroformer"
REVISION = "ac9b0614ab3cd7f77219e18ba494dfd93956c348"
FILENAME = "MelBandRoformer.ckpt"
SHA256 = "87201f4d31afb5bc79993230fc49446918425574db48c01c405e44f365c7559e"
SIZE = 913106900


@dataclass
class RawAudio:
    """A chunk of capture audio at the device's own rate: (frames, channels) float32."""
    data: np.ndarray
    rate: int


def _models_dir() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Echoglass" / "models" / "melbandroformer"


def ensure_weights(on_progress: Callable[[float, float], None] | None = None) -> Path:
    """Download (once) and verify the RoFormer checkpoint; returns its path."""
    d = _models_dir()
    ckpt, ok = d / FILENAME, d / (FILENAME + ".verified")
    if ckpt.exists() and ok.exists() and ok.read_text().strip() == SHA256:
        return ckpt
    import huggingface_hub
    from tqdm.auto import tqdm

    class _Progress(tqdm):
        def __init__(self, *a, **kw):
            kw["disable"] = False
            super().__init__(*a, **kw)

        def update(self, n=1):
            super().update(n)
            if on_progress and self.unit == "B" and self.total:
                on_progress(self.n, self.total)

    log.info("Downloading Mel-Band RoFormer weights (%.1f GB)", SIZE / 1e9)
    path = Path(huggingface_hub.snapshot_download(REPO, revision=REVISION, allow_patterns=[FILENAME],
                                                 local_dir=d, tqdm_class=_Progress)) / FILENAME
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 22):
            h.update(chunk)
    if h.hexdigest() != SHA256:
        path.unlink(missing_ok=True)
        raise RuntimeError("Music mode model failed its checksum; it will be downloaded again next time")
    ok.write_text(SHA256)
    return path


class VocalSeparator:
    def __init__(self, block_s: float = 2.0, context_s: float = 3.0, device: str = "cuda",
                 on_download: Callable[[float, float], None] | None = None):
        import torch
        from bs_roformer import MelBandRoformer

        self._torch = torch
        ckpt = ensure_weights(on_download)
        # config_vocals_mel_band_roformer_kj.yaml
        model = MelBandRoformer(dim=384, depth=6, stereo=True, num_stems=1, time_transformer_depth=1,
                                freq_transformer_depth=1, num_bands=60, dim_head=64, heads=8,
                                attn_dropout=0, ff_dropout=0, flash_attn=True, dim_freqs_in=1025,
                                sample_rate=MODEL_SR, stft_n_fft=2048, stft_hop_length=441,
                                stft_win_length=2048, mask_estimator_depth=2)
        model.load_state_dict(torch.load(ckpt, map_location="cpu", weights_only=True), strict=True)
        self.model = model.to(device).eval()
        self.device = device
        self.block = int(block_s * MODEL_SR)
        self.context = int(context_s * MODEL_SR)
        self._pending = np.zeros((2, 0), np.float32)
        self._history = np.zeros((2, 0), np.float32)
        self._in_rate: int | None = None
        self._resample_in: soxr.ResampleStream | None = None
        self._resample_out = soxr.ResampleStream(MODEL_SR, SAMPLE_RATE, 1, dtype="float32", quality="HQ")
        log.info("Music mode: Mel-Band RoFormer loaded on %s", device)

    def fresh(self) -> "VocalSeparator":
        """Same loaded model, empty stream state (for a new Start)."""
        self._pending = np.zeros((2, 0), np.float32)
        self._history = np.zeros((2, 0), np.float32)
        self._in_rate = None
        self._resample_in = None
        self._resample_out = soxr.ResampleStream(MODEL_SR, SAMPLE_RATE, 1, dtype="float32", quality="HQ")
        return self

    # ---- input -----------------------------------------------------------------------

    def _to_model_rate(self, chunk) -> np.ndarray:
        """-> (2, n) float32 at 44.1 kHz."""
        if isinstance(chunk, RawAudio):
            data, rate = chunk.data, chunk.rate
            if data.ndim == 1:
                data = data[:, None]
            stereo = data[:, :2] if data.shape[1] >= 2 else np.repeat(data[:, :1], 2, axis=1)
        else:  # 16 kHz mono (file input / tests)
            rate = SAMPLE_RATE
            stereo = np.repeat(np.asarray(chunk, np.float32)[:, None], 2, axis=1)
        if rate != self._in_rate:
            self._in_rate = rate
            self._resample_in = (None if rate == MODEL_SR else
                                 soxr.ResampleStream(rate, MODEL_SR, 2, dtype="float32", quality="HQ"))
        stereo = np.ascontiguousarray(stereo, np.float32)
        if self._resample_in is not None:
            stereo = self._resample_in.resample_chunk(stereo)
        return stereo.T

    # ---- separation ------------------------------------------------------------------

    def _separate(self, x: np.ndarray) -> np.ndarray:
        """(2, n) at 44.1 kHz -> mono vocals (n,) at 44.1 kHz."""
        torch = self._torch
        t = torch.from_numpy(np.ascontiguousarray(x))[None].to(self.device)
        with torch.no_grad(), torch.autocast("cuda", dtype=torch.float16):
            y = self.model(t)
        y = y.float()
        while y.dim() > 2:
            y = y[0]
        return y.mean(0).cpu().numpy()

    def _process_block(self, block: np.ndarray) -> np.ndarray:
        x = np.concatenate([self._history, block], axis=1)
        vocals = self._separate(x)[-block.shape[1]:]
        self._history = x[:, -self.context:]
        return self._resample_out.resample_chunk(vocals.astype(np.float32))

    def feed(self, chunk) -> np.ndarray:
        """Returns separated vocals (16 kHz mono); output lags input by up to one block."""
        self._pending = np.concatenate([self._pending, self._to_model_rate(chunk)], axis=1)
        out = []
        while self._pending.shape[1] >= self.block:
            block, self._pending = self._pending[:, :self.block], self._pending[:, self.block:]
            out.append(self._process_block(block))
        return np.concatenate(out) if out else np.zeros(0, np.float32)

    def flush(self) -> np.ndarray:
        if self._pending.shape[1] == 0:
            return np.zeros(0, np.float32)
        block, self._pending = self._pending, np.zeros((2, 0), np.float32)
        out = self._process_block(block)
        return np.concatenate([out, self._resample_out.resample_chunk(np.zeros(0, np.float32), last=True)])

    def warmup(self) -> None:
        self._separate(np.zeros((2, MODEL_SR * 5), np.float32))
