"""Start the Echoglass window.

    .venv\\Scripts\\pythonw run_app.py     (no console)
    .venv\\Scripts\\python run_app.py      (with log output)
"""

import logging
import os
import sys

os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

from PyQt6.QtGui import QIcon  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from livetranslate import settings  # noqa: E402
from livetranslate.ui import theme  # noqa: E402
from livetranslate.ui.main_window import MainWindow  # noqa: E402


def main() -> None:
    # Windowed builds (pythonw / the packaged exe) have no console: stdout/stderr are None,
    # which breaks libraries that print progress. Log to a file instead.
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w")
    settings.migrate_old_name()
    settings.SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname).1s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        handlers=[logging.FileHandler(settings.SETTINGS_DIR / "log.txt", "w", encoding="utf-8"),
                  logging.StreamHandler()])
    for noisy in ("httpx", "httpx2", "openai", "anthropic", "faster_whisper", "huggingface_hub"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    # Without a console, uncaught errors would vanish: put them in log.txt.
    sys.excepthook = lambda *exc: logging.getLogger("crash").error("Uncaught exception", exc_info=exc)

    app = QApplication(sys.argv)
    app.setApplicationName("Echoglass")
    app.setQuitOnLastWindowClosed(False)  # closing the window hides it to the tray
    app.setWindowIcon(QIcon(str(theme.ASSETS / "icon.png")))
    theme.apply(app)
    win = MainWindow(settings.load())
    win.show()
    if len(sys.argv) > 2 and sys.argv[1] == "--selftest":
        _selftest(win, sys.argv[2])
    elif len(sys.argv) > 2 and sys.argv[1] == "--selftest-ocr":
        _selftest_ocr(win, sys.argv[2])
    sys.exit(app.exec())


def _selftest(win, wav_path: str) -> None:
    """Packaged-build check: start, push a WAV through the pipeline, log results, quit."""
    import wave

    import numpy as np
    from PyQt6.QtCore import QTimer

    log = logging.getLogger("selftest")
    with wave.open(wav_path, "rb") as w:
        audio = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768

    win.engine.translated.connect(lambda _id, r: log.info("SELFTEST %s | %s -> %s", r.transcript.language,
                                                          r.transcript.text, r.translation))
    win.engine.running_changed.connect(lambda on: on and win.engine._pipeline.feed(audio))
    if "--music" in sys.argv:
        win.cfg.music_mode = True
    QTimer.singleShot(500, win._toggle_running)
    QTimer.singleShot(90_000, win.quit_app)


def _selftest_ocr(win, image_path: str) -> None:
    """Packaged-build check for screen text: OCR an image, translate the lines, log, quit."""
    import cv2

    from livetranslate.screen.ocr import ScreenOCR
    from livetranslate.translation import create_translator

    log = logging.getLogger("selftest")
    lines = ScreenOCR().read(cv2.imread(image_path))
    tr = create_translator(win.cfg.translation)
    for line in lines:
        out = tr.translate(line.text, None, win.cfg.translation.target_language, [], kind="text") if tr else None
        log.info("SELFTEST-OCR %s -> %s", line.text, out)
    win.quit_app()


if __name__ == "__main__":
    main()
