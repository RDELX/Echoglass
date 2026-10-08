"""Start the Echoglass window.

    .venv\\Scripts\\pythonw run_app.py     (no console)
    .venv\\Scripts\\python run_app.py      (with log output)
"""

import logging
import os
import sys

os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

from PyQt6.QtGui import QIcon  # noqa: E402
from PyQt6.QtNetwork import QLocalServer, QLocalSocket  # noqa: E402
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
    app = QApplication(sys.argv)
    selftest = len(sys.argv) > 2 and sys.argv[1].startswith("--selftest")
    if not selftest and _activate_running_instance():
        return  # another Echoglass is already running and has been brought to the front

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

    app.setApplicationName("Echoglass")
    app.setQuitOnLastWindowClosed(False)  # closing the window hides it to the tray
    app.setWindowIcon(QIcon(str(theme.ASSETS / "icon.png")))
    theme.apply(app)
    win = MainWindow(settings.load())
    win.show()
    if not selftest:
        server = _listen_for_other_instances(win)  # noqa: F841 (kept alive for the app's lifetime)
    if len(sys.argv) > 2 and sys.argv[1] == "--selftest":
        _selftest(win, sys.argv[2])
    elif len(sys.argv) > 2 and sys.argv[1] == "--selftest-ocr":
        _selftest_ocr(win, sys.argv[2])
    elif len(sys.argv) > 2 and sys.argv[1] == "--selftest-romaji":
        from livetranslate.romaji import Romanizer
        r = Romanizer()
        r.load()
        logging.getLogger("selftest").info("SELFTEST-ROMAJI %s -> %s (%s)", sys.argv[2],
                                           r.romaji(sys.argv[2], "ja"), r.error)
        win.quit_app()
        return
    sys.exit(app.exec())


# One Echoglass per Windows user: a second launch asks the running one to show its window.
_INSTANCE_NAME = f"Echoglass-{os.environ.get('USERNAME', 'user')}"


def _activate_running_instance() -> bool:
    sock = QLocalSocket()
    sock.connectToServer(_INSTANCE_NAME)
    if not sock.waitForConnected(500):
        return False
    try:
        import ctypes
        # Let the running instance take the foreground (Windows blocks it otherwise).
        ctypes.windll.user32.AllowSetForegroundWindow(-1)  # ASFW_ANY
    except Exception:
        pass
    sock.write(b"show")
    sock.waitForBytesWritten(500)
    sock.disconnectFromServer()
    return True


def _listen_for_other_instances(win) -> QLocalServer:
    QLocalServer.removeServer(_INSTANCE_NAME)  # clean up after a crashed instance
    server = QLocalServer()
    server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
    if not server.listen(_INSTANCE_NAME):
        logging.getLogger(__name__).warning("Single-instance server: %s", server.errorString())

    def on_connection():
        conn = server.nextPendingConnection()
        if conn is not None:
            conn.disconnected.connect(conn.deleteLater)
            win._show_window()
    server.newConnection.connect(on_connection)
    return server


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
