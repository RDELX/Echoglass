"""Strip above the transcript announcing a new version, with download progress."""

import threading

from PyQt6.QtCore import QObject, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import QApplication, QFrame, QHBoxLayout, QLabel, QProgressBar, QPushButton

from .. import __version__, updater
from . import theme


class _Signals(QObject):
    found = pyqtSignal(object)        # Release | None
    failed = pyqtSignal(str)
    progress = pyqtSignal(int, int)
    downloaded = pyqtSignal(object)   # installer path


class UpdateBanner(QFrame):
    """Hidden until `check()` finds a newer release. `before_install` lets the window
    save settings and stop the pipeline before the app quits for the installer."""

    def __init__(self, before_install, parent=None):
        super().__init__(parent)
        self.before_install = before_install
        self.release: updater.Release | None = None
        self._cancel = False
        self._manual = False
        self.setObjectName("updateBanner")
        self.setStyleSheet(f"""
            #updateBanner {{ background: {theme.ACCENT_DIM}; border: 1px solid {theme.ACCENT};
                             border-radius: 10px; }}
            #updateBanner QLabel {{ color: #dfe3ff; }}
            QProgressBar {{ background: {theme.SURFACE_2}; border: none; border-radius: 4px;
                            max-height: 8px; min-width: 160px; }}
            QProgressBar::chunk {{ background: {theme.ACCENT}; border-radius: 4px; }}
        """)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 8, 8, 8)
        self.text = QLabel()
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.hide()
        self.notes_btn = QPushButton("What's new")
        self.notes_btn.setObjectName("ghost")
        self.notes_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(self.release.url)))
        self.update_btn = QPushButton("Update now")
        self.update_btn.setObjectName("primary")
        self.update_btn.setStyleSheet("padding: 6px 16px; min-width: 0; font-size: 10pt;")
        self.update_btn.clicked.connect(self._start_download)
        self.later_btn = QPushButton("Later")
        self.later_btn.setObjectName("ghost")
        self.later_btn.clicked.connect(self._later)
        lay.addWidget(self.text, 1)
        lay.addWidget(self.bar)
        for b in (self.notes_btn, self.update_btn, self.later_btn):
            lay.addWidget(b)
        self.hide()

        self.sig = _Signals()
        self.sig.found.connect(self._on_found)
        self.sig.failed.connect(self._on_failed)
        self.sig.progress.connect(self._on_progress)
        self.sig.downloaded.connect(self._on_downloaded)

    # ---- checking --------------------------------------------------------------------

    def check(self, manual: bool = False) -> None:
        """Background check. `manual` also reports "up to date" and errors."""
        self._manual = manual

        def run():
            try:
                self.sig.found.emit(updater.check())
            except Exception as e:
                self.sig.failed.emit(f"Couldn't check for updates: {e}")
        threading.Thread(target=run, daemon=True).start()

    def _on_found(self, rel) -> None:
        if rel is None:
            if self._manual:
                self._message(f"You're on the latest version ({__version__}).", hide_after=True)
            return
        self.release = rel
        size = (f"{rel.size / 1e6:.0f} MB" if rel.size < 1e9 else f"{rel.size / 1e9:.1f} GB")
        kind = "quick update" if rel.patch else "full installer"
        self.text.setText(f"Echoglass {rel.version} is available (you have {__version__}). "
                          f"Download: {size}, {kind}.")
        self.update_btn.setVisible(updater.can_self_update())
        self.update_btn.setEnabled(True)
        self.notes_btn.show()
        self.later_btn.setText("Later")
        self.show()

    def _on_failed(self, msg: str) -> None:
        if self._manual or self.bar.isVisible():
            self.bar.hide()
            self._message(msg)

    def _message(self, text: str, hide_after: bool = False) -> None:
        self.text.setText(text)
        self.notes_btn.hide()
        self.update_btn.hide()
        self.later_btn.setText("OK")
        self.show()

    # ---- updating --------------------------------------------------------------------

    def _start_download(self) -> None:
        self._cancel = False
        self.update_btn.setEnabled(False)
        self.notes_btn.hide()
        self.later_btn.setText("Cancel")
        self.bar.setValue(0)
        self.bar.show()
        rel = self.release

        def run():
            try:
                path = updater.download(rel, lambda d, t: self.sig.progress.emit(d, t),
                                        cancelled=lambda: self._cancel)
                self.sig.downloaded.emit(path)
            except Exception as e:
                self.sig.failed.emit(f"Update failed: {e}")
        threading.Thread(target=run, daemon=True).start()

    def _on_progress(self, done: int, total: int) -> None:
        self.bar.setMaximum(1000)
        self.bar.setValue(int(done / max(total, 1) * 1000))
        self.text.setText(f"Downloading Echoglass {self.release.version}… "
                          f"{done / 1e6:.0f} / {total / 1e6:.0f} MB")

    def _on_downloaded(self, path) -> None:
        self.text.setText("Installing the update. Echoglass will restart by itself.")
        self.bar.setMaximum(0)  # busy indicator
        self.later_btn.hide()
        QApplication.processEvents()
        self.before_install()
        updater.install(path, self.release.version)
        QApplication.quit()

    def _later(self) -> None:
        if self.bar.isVisible():
            self._cancel = True
            self.bar.hide()
        self.hide()
