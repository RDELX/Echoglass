"""Main window: settings along the top, the transcript in the middle, status + Start below."""

from collections import deque

from PyQt6.QtCore import QByteArray, Qt
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import (QButtonGroup, QComboBox, QHBoxLayout, QLabel, QMainWindow,
                             QPushButton, QVBoxLayout, QWidget)

from .. import settings
from ..audio import list_loopback_devices
from ..config import Config
from ..translation.languages import LANGUAGES
from . import theme
from .engine import Engine
from .overlay import SubtitleOverlay
from .settings_dialog import SettingsDialog
from .transcript_view import TranscriptView

BACKEND_LABELS = [
    ("ollama", "Ollama (local)"),
    ("lmstudio", "LM Studio (local)"),
    ("claude", "Claude"),
    ("deepl", "DeepL"),
    ("openai", "OpenAI"),
    ("none", "Off (transcribe only)"),
]

STATUS_COLORS = {"idle": theme.MUTED, "busy": theme.WARN, "live": theme.LIVE, "error": theme.ERROR}


def _labelled(label: str, widget: QWidget) -> QWidget:
    box = QWidget()
    lay = QVBoxLayout(box)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(3)
    lbl = QLabel(label)
    lbl.setObjectName("fieldLabel")
    lay.addWidget(lbl)
    lay.addWidget(widget)
    return box


class MainWindow(QMainWindow):
    def __init__(self, cfg: Config):
        super().__init__()
        self.cfg = cfg
        self.engine = Engine(cfg)
        self._timings: deque[tuple[float, float]] = deque(maxlen=10)
        self.overlay = SubtitleOverlay(cfg.overlay)
        self.overlay.set_target_language(cfg.translation.target_language)

        self.setWindowTitle("LiveTranslate")
        self.resize(1180, 720)
        self.setMinimumSize(860, 520)

        root = QWidget()
        root.setObjectName("root")
        lay = QVBoxLayout(root)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(14)
        lay.addLayout(self._build_top_bar())
        self.view = TranscriptView()
        self.view.set_target_language(cfg.translation.target_language)
        self.view.mode = cfg.ui.view_mode
        self.view.change_font_size(cfg.ui.font_size - self.view._font_pt)
        lay.addWidget(self.view, 1)
        lay.addLayout(self._build_bottom_bar())
        self.setCentralWidget(root)

        if cfg.ui.window_geometry:
            self.restoreGeometry(QByteArray.fromBase64(cfg.ui.window_geometry.encode()))
        self.lock_btn.setChecked(cfg.overlay.locked)
        self.lock_btn.setEnabled(False)
        self.overlay_btn.setChecked(cfg.ui.overlay_visible)

        self.engine.status.connect(self._on_status)
        self.engine.running_changed.connect(self._on_running)
        self.engine.original.connect(self._on_original)
        self.engine.translated.connect(self._on_translated)

        QShortcut(QKeySequence("Ctrl+Return"), self, activated=self._toggle_running)
        QShortcut(QKeySequence("Ctrl+="), self, activated=lambda: self.view.change_font_size(1))
        QShortcut(QKeySequence("Ctrl++"), self, activated=lambda: self.view.change_font_size(1))
        QShortcut(QKeySequence("Ctrl+-"), self, activated=lambda: self.view.change_font_size(-1))
        QShortcut(QKeySequence("Ctrl+L"), self, activated=self.view_clear)
        QShortcut(QKeySequence("Ctrl+O"), self, activated=self.overlay_btn.toggle)

        self._on_status("Ready", "idle")

    # ---- layout ----------------------------------------------------------------------

    def _build_top_bar(self) -> QHBoxLayout:
        bar = QHBoxLayout()
        bar.setSpacing(10)

        name = QLabel("LiveTranslate")
        name.setObjectName("appName")
        bar.addWidget(name, 0, Qt.AlignmentFlag.AlignBottom)
        bar.addSpacing(18)

        self.source = QComboBox()
        self.source.addItem("Auto-detect", None)
        for code, (label, *_ ) in LANGUAGES.items():
            self.source.addItem(label, code)
        self.source.setCurrentIndex(max(0, self.source.findData(self.cfg.asr.language)))
        self.source.setToolTip("Language being spoken. Auto-detect works for most videos;\n"
                               "pick one if short lines get detected wrongly.")
        self.source.currentIndexChanged.connect(
            lambda: self.engine.set_source_language(self.source.currentData()))

        self.target = QComboBox()
        for code, (label, *_ ) in LANGUAGES.items():
            self.target.addItem(label, code)
        self.target.setCurrentIndex(self.target.findData(self.cfg.translation.target_language))
        self.target.currentIndexChanged.connect(self._on_target_changed)

        arrow = QLabel("→")
        arrow.setObjectName("arrow")
        bar.addWidget(_labelled("From", self.source))
        bar.addWidget(arrow, 0, Qt.AlignmentFlag.AlignBottom)
        bar.addWidget(_labelled("To", self.target))
        bar.addSpacing(10)

        self.backend = QComboBox()
        for key, label in BACKEND_LABELS:
            self.backend.addItem(label, key)
        self.backend.setCurrentIndex(self.backend.findData(self.cfg.translation.backend))
        self.backend.setToolTip("Local models run on your GPU for free.\n"
                                "Cloud services read their API key from environment variables\n"
                                "(ANTHROPIC_API_KEY, DEEPL_API_KEY, OPENAI_API_KEY) for now.")
        self.backend.currentIndexChanged.connect(
            lambda: self.engine.set_backend(self.backend.currentData()))
        bar.addWidget(_labelled("Translator", self.backend))

        bar.addStretch(1)

        self.music = QPushButton("♪  Music mode")
        self.music.setObjectName("pill")
        self.music.setCheckable(True)
        self.music.setChecked(self.cfg.music_mode)
        self.music.setCursor(Qt.CursorShape.PointingHandCursor)
        self.music.setToolTip("Separate vocals from instruments before recognising speech.\n"
                              "Use for songs or videos with loud background music.\n"
                              "Adds about 2 seconds of delay.")
        self.music.toggled.connect(self._on_music_toggled)
        bar.addWidget(self.music, 0, Qt.AlignmentFlag.AlignBottom)

        self.overlay_btn = QPushButton("▭  Overlay")
        self.overlay_btn.setObjectName("pill")
        self.overlay_btn.setCheckable(True)
        self.overlay_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.overlay_btn.setToolTip("Floating subtitles on top of everything, e.g. fullscreen video (Ctrl+O)")
        self.overlay_btn.toggled.connect(self._on_overlay_toggled)
        bar.addWidget(self.overlay_btn, 0, Qt.AlignmentFlag.AlignBottom)

        self.lock_btn = QPushButton("Lock")
        self.lock_btn.setObjectName("pill")
        self.lock_btn.setCheckable(True)
        self.lock_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.lock_btn.setToolTip("Locked: clicks pass through the subtitles to the video.\n"
                                 "Unlock to move or resize them.")
        self.lock_btn.toggled.connect(self._on_lock_toggled)
        bar.addWidget(self.lock_btn, 0, Qt.AlignmentFlag.AlignBottom)

        settings_btn = QPushButton("Settings")
        settings_btn.setObjectName("pill")
        settings_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        settings_btn.setToolTip("Translator models and API keys, speech recognition, overlay look")
        settings_btn.clicked.connect(self._open_settings)
        bar.addWidget(settings_btn, 0, Qt.AlignmentFlag.AlignBottom)
        return bar

    def _build_bottom_bar(self) -> QHBoxLayout:
        bar = QHBoxLayout()
        bar.setSpacing(10)

        self.dot = QLabel()
        self.dot.setFixedSize(8, 8)
        self.status_text = QLabel()
        self.status_text.setObjectName("statusText")
        self.stats = QLabel()
        self.stats.setObjectName("statsText")
        bar.addWidget(self.dot)
        bar.addWidget(self.status_text)
        bar.addSpacing(12)
        bar.addWidget(self.stats)
        bar.addStretch(1)

        seg = QWidget()
        seg.setObjectName("segment")
        seg_lay = QHBoxLayout(seg)
        seg_lay.setContentsMargins(3, 3, 3, 3)
        seg_lay.setSpacing(2)
        group = QButtonGroup(self)
        for mode, label in (("lines", "Lines"), ("paragraph", "Paragraph")):
            b = QPushButton(label)
            b.setCheckable(True)
            b.setChecked(mode == self.cfg.ui.view_mode)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, m=mode: self._set_view_mode(m))
            group.addButton(b)
            seg_lay.addWidget(b)
        seg.setToolTip("Lines: each sentence next to its translation.\n"
                       "Paragraph: continuous text, easier to read along.")
        bar.addWidget(seg)

        clear = QPushButton("Clear")
        clear.setObjectName("ghost")
        clear.setToolTip("Clear the transcript (Ctrl+L)")
        clear.setCursor(Qt.CursorShape.PointingHandCursor)
        clear.clicked.connect(self.view_clear)
        bar.addWidget(clear)
        bar.addSpacing(8)

        self.device = QComboBox()
        self.device.setToolTip("Which playback device to listen to")
        self.device.addItem("Default output device", None)
        try:
            for d in list_loopback_devices():
                self.device.addItem(d["name"].replace(" [Loopback]", ""), d["index"])
        except Exception:
            pass
        if self.cfg.device_name:
            self.device.setCurrentIndex(max(0, self.device.findText(self.cfg.device_name)))
            self.cfg.device_index = self.device.currentData()
        self.device.currentIndexChanged.connect(self._on_device_changed)
        self.device.setMinimumWidth(220)
        bar.addWidget(self.device)

        self.start_btn = QPushButton("Start")
        self.start_btn.setObjectName("primary")
        self.start_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.start_btn.setToolTip("Start / stop (Ctrl+Enter)")
        self.start_btn.clicked.connect(self._toggle_running)
        bar.addWidget(self.start_btn)
        return bar

    # ---- actions ---------------------------------------------------------------------

    def view_clear(self) -> None:
        self.view.clear()
        self.overlay.clear()

    def _set_view_mode(self, mode: str) -> None:
        self.cfg.ui.view_mode = mode
        self.view.set_mode(mode)

    def _on_overlay_toggled(self, on: bool) -> None:
        self.cfg.ui.overlay_visible = on
        self.lock_btn.setEnabled(on)
        if on:
            self.overlay.show()
            self.overlay.show_entries(self.view.entries)
        else:
            self.overlay.hide()

    def _on_lock_toggled(self, locked: bool) -> None:
        self.lock_btn.setText("Locked" if locked else "Lock")
        self.overlay.set_locked(locked)

    def _open_settings(self) -> None:
        dlg = SettingsDialog(self.cfg, self)
        if not dlg.exec() or dlg.result_cfg is None:
            return
        new = dlg.result_cfg
        restart_needed = (new.asr.model != self.cfg.asr.model or new.vad != self.cfg.vad)
        for section in ("asr", "vad", "translation", "overlay"):
            setattr(self.cfg, section, getattr(new, section))
        self.overlay.cfg = self.cfg.overlay
        self.overlay.apply_config()
        self.engine.cfg = self.cfg
        self._save_settings()
        if self.engine.running:
            self.engine.set_backend(self.cfg.translation.backend)
            if restart_needed:
                self._on_status("Saved. Speech settings apply the next time you press Start.", "live")

    def _save_settings(self) -> None:
        self.cfg.ui.font_size = self.view._font_pt
        self.cfg.ui.window_geometry = bytes(self.saveGeometry().toBase64()).decode()
        self.overlay.save_geometry()
        try:
            settings.save(self.cfg)
        except Exception as e:
            self._on_status(f"Couldn't save settings: {e}", "error")

    def _toggle_running(self) -> None:
        if self.engine.busy:
            return
        self.start_btn.setEnabled(False)
        if self.engine.running:
            self.engine.stop()
        else:
            self.start_btn.setText("Starting…")
            self.engine.start()

    def _on_music_toggled(self, on: bool) -> None:
        self.cfg.music_mode = on
        if self.engine.running:
            self.start_btn.setEnabled(False)
            self.engine.restart()

    def _on_device_changed(self) -> None:
        self.cfg.device_index = self.device.currentData()
        self.cfg.device_name = self.device.currentText() if self.cfg.device_index is not None else None
        if self.engine.running:
            self.start_btn.setEnabled(False)
            self.engine.restart()

    def _on_target_changed(self) -> None:
        code = self.target.currentData()
        self.engine.set_target_language(code)
        self.view.set_target_language(code)
        self.overlay.set_target_language(code)

    # ---- engine signals --------------------------------------------------------------

    def _on_status(self, text: str, kind: str) -> None:
        self.status_text.setText(text)
        self.status_text.setProperty("kind", kind)
        self.status_text.style().unpolish(self.status_text)
        self.status_text.style().polish(self.status_text)
        self.dot.setStyleSheet(f"background:{STATUS_COLORS.get(kind, theme.MUTED)};"
                               "border-radius:4px;")
        if kind in ("idle", "error") and not self.engine.running:
            self.start_btn.setText("Start")
            self.start_btn.setEnabled(True)

    def _on_running(self, running: bool) -> None:
        self.start_btn.setText("Stop" if running else "Start")
        self.start_btn.setProperty("running", running)
        self.start_btn.style().unpolish(self.start_btn)
        self.start_btn.style().polish(self.start_btn)
        self.start_btn.setEnabled(True)
        if running and not self.view.entries:
            self.view.set_empty_message("Listening…", "Play something with speech or singing.")
        elif not running:
            self.view.set_empty_message("Nothing yet", "Press Start, then play a video or song.\n"
                                        "Speech appears here as it's recognised.")
            self.stats.clear()

    def _on_original(self, entry_id: int, t) -> None:
        translating = self.cfg.translation.backend != "none"
        self.view.add_original(entry_id, t, translating)
        if self.overlay.isVisible():
            self.overlay.show_entries(self.view.entries)

    def _on_translated(self, entry_id: int, r) -> None:
        self.view.set_translation(entry_id, r)
        if self.overlay.isVisible():
            self.overlay.show_entries(self.view.entries)
        self._timings.append((r.transcript.asr_seconds, r.seconds))
        asr = sum(a for a, _ in self._timings) / len(self._timings)
        mt = sum(m for _, m in self._timings) / len(self._timings)
        self.stats.setText(f"recognition {asr:.1f}s · translation {mt:.1f}s"
                           if mt else f"recognition {asr:.1f}s")
        if r.error:
            self._on_status(f"Translation failed: {r.error}", "error")

    def closeEvent(self, ev) -> None:
        self._save_settings()
        self.overlay.close()
        self.hide()
        self.engine.shutdown()
        super().closeEvent(ev)
