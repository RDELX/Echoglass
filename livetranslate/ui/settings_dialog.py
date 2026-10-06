"""Settings window: translator endpoints/models/keys, speech recognition, overlay look."""

import copy
import json
import os
import sys
import threading
import urllib.request
from pathlib import Path

from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFormLayout,
                             QHBoxLayout, QLabel, QLineEdit, QPushButton, QSlider, QSpinBox,
                             QTabWidget, QVBoxLayout, QWidget)

from .. import settings
from ..config import Config

WHISPER_MODELS = [
    ("large-v3", "large-v3 (best accuracy)"),
    ("large-v3-turbo", "large-v3-turbo (faster, slightly less accurate)"),
    ("medium", "medium (lighter)"),
]
CLAUDE_MODELS = ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-4-5"]
SENSITIVITY = [(0.5, "Normal"), (0.35, "High (quiet or distant voices)"), (0.65, "Low (noisy audio)")]


def _section(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet("font-weight: 600; margin-top: 10px;")
    return lbl


def _note(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("emptyHint")
    lbl.setWordWrap(True)
    return lbl


class _KeyField(QLineEdit):
    """Password field that shows whether a key is already stored, without revealing it."""

    def __init__(self, has_key: bool):
        super().__init__()
        self.setEchoMode(QLineEdit.EchoMode.Password)
        self.has_key = has_key
        self.cleared = False
        self.setPlaceholderText("Saved in Windows Credential Manager" if has_key
                                else "Paste your API key")


def _fetch_models(url: str) -> list[str]:
    """Model ids from an OpenAI-compatible server; [] if it isn't running. Call off the UI thread."""
    try:
        with urllib.request.urlopen(url.rstrip("/") + "/models", timeout=1.5) as r:
            return sorted(m["id"] for m in json.load(r).get("data", []))
    except Exception:
        return []


class _ModelFetcher(QObject):
    done = pyqtSignal(object, list)  # combo, model ids

    def fetch(self, combo: QComboBox, url: str) -> None:
        threading.Thread(target=lambda: self.done.emit(combo, _fetch_models(url)),
                         daemon=True).start()


def extension_folder() -> Path:
    """browser-extension/ next to the exe when installed, or in the repo when run from source."""
    base = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parents[2]
    return base / "browser-extension"


def _open_extension_folder() -> None:
    os.startfile(extension_folder())


class SettingsDialog(QDialog):
    def __init__(self, cfg: Config, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(560)
        self.cfg = cfg
        self.result_cfg: Config | None = None
        self._new_keys: dict[str, str | None] = {}
        # Model lists load in the background so a stopped local server can't freeze the UI.
        self._fetcher = _ModelFetcher()
        self._fetcher.done.connect(self._fill_models)

        tabs = QTabWidget()
        tabs.addTab(self._general_tab(), "General")
        tabs.addTab(self._translation_tab(), "Translation")
        tabs.addTab(self._speech_tab(), "Speech recognition")
        tabs.addTab(self._overlay_tab(), "Subtitle overlay")

        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        save = QPushButton("Save")
        save.setObjectName("primary")
        save.setDefault(True)
        save.clicked.connect(self._save)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(cancel)
        buttons.addWidget(save)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 18, 18, 18)
        lay.addWidget(tabs)
        lay.addLayout(buttons)
        self.setStyleSheet("QTabWidget::pane { border: 1px solid #262b35; border-radius: 8px;"
                           " padding: 8px; } QTabBar::tab { padding: 6px 14px; color: #7c8495; }"
                           " QTabBar::tab:selected { color: #e7e9ee; }"
                           " QLineEdit, QSpinBox, QDoubleSpinBox { background: #1c2028;"
                           " border: 1px solid #262b35; border-radius: 8px; padding: 5px 8px; }")

    # ---- tabs ------------------------------------------------------------------------

    def _general_tab(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.close_to_tray = QCheckBox("Closing the window keeps LiveTranslate running in the tray")
        self.close_to_tray.setChecked(self.cfg.ui.close_to_tray)
        form.addRow("Window", self.close_to_tray)
        self.check_updates = QCheckBox("Check for new versions when LiveTranslate starts")
        self.check_updates.setChecked(self.cfg.ui.check_updates)
        form.addRow("Updates", self.check_updates)

        form.addRow(_section("Browser extension"))
        self.api_enabled = QCheckBox("Allow the LiveTranslate Chrome extension to connect")
        self.api_enabled.setChecked(self.cfg.api.enabled)
        form.addRow("", self.api_enabled)
        self.api_port = QSpinBox()
        self.api_port.setRange(1024, 65535)
        self.api_port.setValue(self.cfg.api.port)
        form.addRow("Port", self.api_port)
        folder = QPushButton("Open extension folder")
        folder.setObjectName("ghost")
        folder.clicked.connect(_open_extension_folder)
        form.addRow("", folder)
        form.addRow(_note("To install: open chrome://extensions, turn on Developer mode, click "
                          "“Load unpacked” and choose the extension folder. Only that extension "
                          "can talk to the app, and only from this PC. If you change the port, "
                          "set the same port in the extension's popup."))
        return w

    def _translation_tab(self) -> QWidget:
        t = self.cfg.translation
        w = QWidget()
        form = QFormLayout(w)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        form.addRow(_section("Ollama (local)"))
        self.ollama_url = QLineEdit(t.ollama_url)
        self.ollama_model = self._model_combo(t.ollama_url, t.ollama_model)
        form.addRow("Server", self.ollama_url)
        form.addRow("Model", self._with_refresh(self.ollama_model, self.ollama_url))

        form.addRow(_section("LM Studio (local)"))
        self.lms_url = QLineEdit(t.lmstudio_url)
        self.lms_model = self._model_combo(t.lmstudio_url, t.lmstudio_model)
        form.addRow("Server", self.lms_url)
        form.addRow("Model", self._with_refresh(self.lms_model, self.lms_url))

        form.addRow(_section("Claude"))
        self.claude_key = _KeyField(bool(t.anthropic_api_key))
        self.claude_model = QComboBox()
        self.claude_model.setEditable(True)
        self.claude_model.addItems(CLAUDE_MODELS)
        self.claude_model.setCurrentText(t.claude_model)
        form.addRow("API key", self.claude_key)
        form.addRow("Model", self.claude_model)

        form.addRow(_section("DeepL"))
        self.deepl_key = _KeyField(bool(t.deepl_api_key))
        form.addRow("API key", self.deepl_key)

        form.addRow(_section("OpenAI"))
        self.openai_key = _KeyField(bool(t.openai_api_key))
        self.openai_model = QLineEdit(t.openai_model)
        form.addRow("API key", self.openai_key)
        form.addRow("Model", self.openai_model)

        form.addRow(_section("All translators"))
        self.context_lines = QSpinBox()
        self.context_lines.setRange(0, 10)
        self.context_lines.setValue(t.context_lines)
        self.context_lines.setToolTip("Previous lines sent along so names and tone stay consistent")
        form.addRow("Context lines", self.context_lines)
        form.addRow(_note("API keys are stored in Windows Credential Manager, never in the "
                          "settings file. Leave a key field empty to keep the saved key."))
        return w

    def _speech_tab(self) -> QWidget:
        a, v = self.cfg.asr, self.cfg.vad
        w = QWidget()
        form = QFormLayout(w)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.whisper = QComboBox()
        for key, label in WHISPER_MODELS:
            self.whisper.addItem(label, key)
        self.whisper.setCurrentIndex(max(0, self.whisper.findData(a.model)))
        form.addRow("Whisper model", self.whisper)

        self.sensitivity = QComboBox()
        for thr, label in SENSITIVITY:
            self.sensitivity.addItem(label, thr)
        idx = min(range(len(SENSITIVITY)), key=lambda i: abs(SENSITIVITY[i][0] - v.threshold))
        self.sensitivity.setCurrentIndex(idx)
        form.addRow("Speech detection", self.sensitivity)

        self.max_len = QDoubleSpinBox()
        self.max_len.setRange(4, 15)
        self.max_len.setSuffix(" s")
        self.max_len.setValue(v.soft_max_s)
        self.max_len.setToolTip("Long monologues are split into lines around this length")
        form.addRow("Line length", self.max_len)

        self.pause = QSpinBox()
        self.pause.setRange(200, 1500)
        self.pause.setSingleStep(100)
        self.pause.setSuffix(" ms")
        self.pause.setValue(v.min_silence_ms)
        self.pause.setToolTip("How long a pause ends a line. Shorter = faster subtitles, "
                              "but sentences get split more often")
        form.addRow("Pause that ends a line", self.pause)
        form.addRow(_note("Changing the Whisper model downloads it on first use "
                          "and takes effect the next time you press Start."))
        return w

    def _overlay_tab(self) -> QWidget:
        o = self.cfg.overlay
        w = QWidget()
        form = QFormLayout(w)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.ov_font = QSpinBox()
        self.ov_font.setRange(12, 72)
        self.ov_font.setValue(o.font_size)
        form.addRow("Text size", self.ov_font)

        self.ov_opacity = QSlider(Qt.Orientation.Horizontal)
        self.ov_opacity.setRange(0, 100)
        self.ov_opacity.setValue(int(o.background_opacity * 100))
        form.addRow("Background", self.ov_opacity)

        self.ov_lines = QSpinBox()
        self.ov_lines.setRange(1, 4)
        self.ov_lines.setValue(o.lines)
        form.addRow("Subtitles on screen", self.ov_lines)

        self.ov_original = QCheckBox("Show the original above the translation")
        self.ov_original.setChecked(o.show_original)
        form.addRow("", self.ov_original)

        self.ov_hide = QDoubleSpinBox()
        self.ov_hide.setRange(2, 60)
        self.ov_hide.setSuffix(" s")
        self.ov_hide.setValue(o.hide_after_s)
        form.addRow("Hide after silence", self.ov_hide)
        return w

    # ---- helpers ---------------------------------------------------------------------

    def _model_combo(self, url: str, current: str) -> QComboBox:
        c = QComboBox()
        c.setEditable(True)
        c.setCurrentText(current)
        self._fetcher.fetch(c, url)
        return c

    @staticmethod
    def _fill_models(combo: QComboBox, models: list) -> None:
        cur = combo.currentText()
        combo.clear()
        combo.addItems(models)
        combo.setCurrentText(cur)
        if not models:
            combo.lineEdit().setPlaceholderText("Server not running — type a model name")

    def _with_refresh(self, combo: QComboBox, url_field: QLineEdit) -> QWidget:
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        btn = QPushButton("Refresh")
        btn.setObjectName("ghost")
        btn.setToolTip("Ask the server which models are installed")

        btn.clicked.connect(lambda: self._fetcher.fetch(combo, url_field.text()))
        lay.addWidget(combo, 1)
        lay.addWidget(btn)
        return w

    def _save(self) -> None:
        cfg = copy.deepcopy(self.cfg)
        t = cfg.translation
        t.ollama_url, t.ollama_model = self.ollama_url.text().strip(), self.ollama_model.currentText().strip()
        t.lmstudio_url, t.lmstudio_model = self.lms_url.text().strip(), self.lms_model.currentText().strip()
        t.claude_model = self.claude_model.currentText().strip()
        t.openai_model = self.openai_model.text().strip()
        t.context_lines = self.context_lines.value()
        for field, (user, _env), box in (
                ("anthropic_api_key", settings.API_KEYS["anthropic_api_key"], self.claude_key),
                ("deepl_api_key", settings.API_KEYS["deepl_api_key"], self.deepl_key),
                ("openai_api_key", settings.API_KEYS["openai_api_key"], self.openai_key)):
            if box.text().strip():
                settings.set_api_key(user, box.text().strip())
                setattr(t, field, box.text().strip())

        cfg.asr.model = self.whisper.currentData()
        cfg.vad.threshold = self.sensitivity.currentData()
        cfg.vad.neg_threshold = max(0.15, cfg.vad.threshold - 0.15)
        cfg.vad.soft_max_s = self.max_len.value()
        cfg.vad.hard_max_s = max(cfg.vad.soft_max_s + 4, 15.0)
        cfg.vad.min_silence_ms = self.pause.value()

        cfg.ui.close_to_tray = self.close_to_tray.isChecked()
        cfg.ui.check_updates = self.check_updates.isChecked()
        cfg.api.enabled = self.api_enabled.isChecked()
        cfg.api.port = self.api_port.value()

        o = cfg.overlay
        o.font_size = self.ov_font.value()
        o.background_opacity = self.ov_opacity.value() / 100
        o.lines = self.ov_lines.value()
        o.show_original = self.ov_original.isChecked()
        o.hide_after_s = self.ov_hide.value()

        self.result_cfg = cfg
        self.accept()
