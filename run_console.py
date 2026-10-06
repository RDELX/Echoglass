"""Console runner: capture system audio, transcribe with Whisper, translate, print.

    .venv\\Scripts\\python run_console.py               # any language -> English via local Ollama
    .venv\\Scripts\\python run_console.py --translator claude   # or deepl/openai/lmstudio/none
    .venv\\Scripts\\python run_console.py --lang ja     # force the source language
    .venv\\Scripts\\python run_console.py --list-devices
    .venv\\Scripts\\python run_console.py --file clip.wav   # run on a 16-bit WAV instead
"""

import argparse
import logging
import os
import sys
import time
import wave

import numpy as np
import soxr

from livetranslate.config import Config

# Windows without Developer Mode can't symlink; HF falls back to copies, which is fine.
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")


def _print_devices() -> None:
    from livetranslate.audio import list_loopback_devices
    for d in list_loopback_devices():
        mark = "*" if d["isDefault"] else " "
        print(f"{mark} [{d['index']:>3}] {d['name']}  ({int(d['defaultSampleRate'])} Hz, "
              f"{d['maxInputChannels']} ch)")


def _load_wav(path: str) -> np.ndarray:
    with wave.open(path, "rb") as w:
        if w.getsampwidth() != 2:
            sys.exit("Only 16-bit PCM WAV files are supported")
        rate, ch = w.getframerate(), w.getnchannels()
        data = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    audio = data.reshape(-1, ch).mean(axis=1).astype(np.float32) / 32768
    return soxr.resample(audio, rate, 16000) if rate != 16000 else audio


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lang", default="auto",
                    help="source language code (ko, ja, zh...), or 'auto' to detect (default)")
    ap.add_argument("--model", default="large-v3")
    ap.add_argument("--device", type=int, default=None, help="loopback device index (see --list-devices)")
    ap.add_argument("--list-devices", action="store_true")
    ap.add_argument("--file", help="transcribe a 16-bit WAV file instead of live audio")
    ap.add_argument("--to", default="en", help="target language code (default: en)")
    ap.add_argument("--translator", default="ollama",
                    help="ollama | lmstudio | openai | deepl | claude | none (default: ollama)")
    ap.add_argument("--llm-model", help="model name for the chosen LLM backend")
    ap.add_argument("--music", action="store_true",
                    help="music mode: isolate vocals first (songs, videos with loud background music)")
    ap.add_argument("--seconds", type=float, help="stop automatically after this many seconds")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname).1s %(name)s: %(message)s", datefmt="%H:%M:%S")
    for noisy in ("httpx", "httpx2", "openai", "anthropic"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    if not args.verbose:
        logging.getLogger("faster_whisper").setLevel(logging.WARNING)
    sys.stdout.reconfigure(encoding="utf-8")

    if args.list_devices:
        _print_devices()
        return

    cfg = Config.default()
    cfg.asr.model = args.model
    cfg.asr.language = None if args.lang == "auto" else args.lang
    cfg.device_index = args.device
    cfg.music_mode = args.music
    cfg.sync_music_mode()
    cfg.asr.live_captions = False  # the console only prints finished lines
    tc = cfg.translation
    tc.backend, tc.target_language = args.translator, args.to
    if args.llm_model:
        setattr(tc, {"ollama": "ollama_model", "lmstudio": "lmstudio_model",
                     "openai": "openai_model", "claude": "claude_model"}.get(tc.backend, "_unused"),
                args.llm_model)

    from livetranslate.pipeline import Pipeline
    from livetranslate.translation import Translated, TranslationWorker, create_translator

    translator = create_translator(tc)
    if translator is not None:
        logging.info("Translating to %s with %s", tc.target_language, translator.label)

    t_start = time.perf_counter()

    def show(r: Translated) -> None:
        t = r.transcript
        # lag = wall time since capture start minus the moment the utterance ended
        lag = (time.perf_counter() - t_start) - (t.start + t.duration)
        timing = f"asr {t.asr_seconds:.2f}s" + (f", mt {r.seconds:.2f}s" if r.seconds else "")
        if not args.file:
            timing += f", lag {lag:.1f}s"
        print(f"[{t.start:7.1f}s] {t.language} | {t.text}", flush=True)
        if r.translation:
            print(f"{'':10} {tc.target_language} | {r.translation}", flush=True)
        elif r.error:
            print(f"{'':10} !! translation failed: {r.error}", flush=True)
        print(f"{'':10} ({timing})", flush=True)

    worker = TranslationWorker(translator, tc.target_language, tc.context_lines, show)
    pipe = Pipeline(cfg, on_transcript=worker.submit)
    pipe.transcriber.warmup()
    worker.start()
    if translator is not None:
        worker.warmup()

    if args.file:
        audio = _load_wav(args.file)
        t_start = time.perf_counter()
        pipe.start_without_capture()
        pipe.feed(audio)
        pipe.stop()
        worker.stop()
        return

    t_start = time.perf_counter()
    pipe.start()
    print(f"Listening on '{pipe.device_name}'. Play something; Ctrl+C to stop.", flush=True)
    try:
        while args.seconds is None or time.perf_counter() - t_start < args.seconds:
            time.sleep(0.2)
    except KeyboardInterrupt:
        print("Stopping...", flush=True)
    finally:
        pipe.stop()
        worker.stop()


if __name__ == "__main__":
    main()
