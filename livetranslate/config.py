"""Runtime settings. Saved to disk by `settings.py`."""

from dataclasses import dataclass, field


@dataclass
class AsrConfig:
    model: str = "large-v3"
    device: str = "cuda"
    compute_type: str = "float16"
    language: str | None = None  # None = auto-detect per utterance; or force e.g. "ja"
    beam_size: int = 5
    # Drop segments Whisper itself thinks are not speech. Music mode lowers this, because
    # leftover instruments make Whisper invent "Thank you." etc. with high no_speech_prob.
    max_no_speech_prob: float = 1.0
    drop_music_phantoms: bool = False  # music mode: drop lone "Thank you." etc.


@dataclass
class VadConfig:
    threshold: float = 0.5          # speech probability that starts an utterance
    neg_threshold: float = 0.35     # probability below which a frame counts as silence
    min_silence_ms: int = 500       # silence that closes an utterance
    min_speech_ms: int = 250        # shorter utterances are dropped
    pre_roll_ms: int = 300          # audio kept before speech onset
    soft_max_s: float = 8.0         # after this, cut at the next dip in speech
    hard_max_s: float = 15.0        # never let an utterance grow past this


@dataclass
class TranslationConfig:
    backend: str = "ollama"         # ollama | lmstudio | openai | deepl | claude | none
    target_language: str = "en"
    context_lines: int = 3          # previous lines sent along for consistency
    ollama_url: str = "http://localhost:11434/v1"
    ollama_model: str = "gemma4:e4b-it-qat"
    lmstudio_url: str = "http://localhost:1234/v1"
    lmstudio_model: str = ""        # empty = whatever model LM Studio has loaded
    openai_model: str = "gpt-5-mini"
    claude_model: str = "claude-opus-5-5"
    claude_effort: str = "low"
    # Keys are never written to settings.json: settings.py keeps them in Windows Credential
    # Manager and fills these in at load. Environment variables are the fallback.
    openai_api_key: str | None = None
    deepl_api_key: str | None = None
    anthropic_api_key: str | None = None


@dataclass
class OverlayConfig:
    font_size: int = 26
    show_original: bool = True      # small original line above the translation
    background_opacity: float = 0.55
    lines: int = 2                  # how many recent subtitles to keep on screen
    hide_after_s: float = 8.0       # fade out when nobody has spoken for this long
    locked: bool = False            # click-through
    geometry: list[int] | None = None  # x, y, w, h


@dataclass
class UiConfig:
    view_mode: str = "lines"        # lines | paragraph
    font_size: float = 13.0
    window_geometry: str | None = None  # Qt saveGeometry(), base64
    overlay_visible: bool = False


@dataclass
class Config:
    asr: AsrConfig
    vad: VadConfig
    translation: TranslationConfig
    overlay: OverlayConfig = field(default_factory=OverlayConfig)
    ui: UiConfig = field(default_factory=UiConfig)
    device_index: int | None = None  # None = loopback of the default output device
    device_name: str | None = None   # saved instead of the index, which can change
    music_mode: bool = False         # isolate vocals with Demucs first (songs, loud BGM)

    def sync_music_mode(self) -> None:
        """Music mode also tightens Whisper's filters against instrumental phantoms."""
        self.asr.max_no_speech_prob = 0.75 if self.music_mode else 1.0
        self.asr.drop_music_phantoms = self.music_mode

    @classmethod
    def default(cls) -> "Config":
        return cls(asr=AsrConfig(), vad=VadConfig(), translation=TranslationConfig())
