"""Diagnostic: record loopback audio to a WAV and log Silero VAD probabilities.

    .venv\\Scripts\\python tools\\record_probe.py out.wav --seconds 60
"""

import argparse
import queue
import sys
import time
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from livetranslate.audio import LoopbackCapture  # noqa: E402
from pysilero_vad import SileroVoiceActivityDetector  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--seconds", type=float, default=60)
    args = ap.parse_args()

    q: "queue.Queue[np.ndarray]" = queue.Queue()
    cap = LoopbackCapture(q)
    cap.start()
    vad = SileroVoiceActivityDetector()
    chunks, pending, probs = [], np.zeros(0, np.float32), []
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < args.seconds:
        try:
            c = q.get(timeout=0.2)
        except queue.Empty:
            continue
        chunks.append(c)
        pending = np.concatenate([pending, c])
        while len(pending) >= 512:
            probs.append(vad.process_samples(pending[:512].tolist()))
            pending = pending[512:]
    cap.stop()

    audio = np.concatenate(chunks) if chunks else np.zeros(0, np.float32)
    with wave.open(args.out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes((np.clip(audio, -1, 1) * 32767).astype(np.int16).tobytes())

    p = np.array(probs)
    print(f"captured {len(audio) / 16000:.1f}s, rms {np.sqrt(np.mean(audio ** 2)) if audio.size else 0:.4f}")
    if p.size:
        print(f"VAD frames {p.size}: mean {p.mean():.2f}, >0.5 {np.mean(p > 0.5):.0%}, "
              f">0.3 {np.mean(p > 0.3):.0%}, >0.15 {np.mean(p > 0.15):.0%}")
        per_sec = p[: len(p) // 31 * 31].reshape(-1, 31).max(axis=1)
        print("max prob per second:", " ".join(f"{x:.1f}" for x in per_sec))


if __name__ == "__main__":
    main()
