"""Start the LiveTranslate window.

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
    settings.SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname).1s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        handlers=[logging.FileHandler(settings.SETTINGS_DIR / "log.txt", "w", encoding="utf-8"),
                  logging.StreamHandler()])
    for noisy in ("httpx", "httpx2", "openai", "anthropic", "faster_whisper", "huggingface_hub"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    app = QApplication(sys.argv)
    app.setApplicationName("LiveTranslate")
    app.setWindowIcon(QIcon(str(theme.ASSETS / "icon.png")))
    theme.apply(app)
    win = MainWindow(settings.load())
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
