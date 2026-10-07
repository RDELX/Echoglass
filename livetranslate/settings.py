"""Load/save `Config` as JSON in %APPDATA%\\Echoglass, with API keys in the OS keyring."""

import dataclasses
import json
import logging
import os
from pathlib import Path

from .config import (ApiConfig, AsrConfig, Config, OverlayConfig, ScreenConfig, TranslationConfig,
                     UiConfig, VadConfig)

log = logging.getLogger(__name__)

SETTINGS_DIR = Path(os.environ.get("APPDATA", Path.home())) / "Echoglass"
SETTINGS_FILE = SETTINGS_DIR / "settings.json"

KEYRING_SERVICE = "Echoglass"

# Before v0.9.0 the app was called LiveTranslate and kept its data under that name.
_OLD_NAME = "LiveTranslate"
# config field -> (keyring user name, environment variable fallback)
API_KEYS = {
    "openai_api_key": ("openai", "OPENAI_API_KEY"),
    "deepl_api_key": ("deepl", "DEEPL_API_KEY"),
    "anthropic_api_key": ("anthropic", "ANTHROPIC_API_KEY"),
}

# Runtime-only fields that must not be persisted.
_SKIP = {"asr": {"max_no_speech_prob", "drop_music_phantoms", "device", "compute_type"},
         "translation": set(API_KEYS), "": {"device_index"}}


def migrate_old_name() -> None:
    """One-time move of LiveTranslate-era settings, models and API keys to Echoglass, so
    nobody has to set things up or download the 3 GB speech model again."""
    appdata = Path(os.environ.get("APPDATA", Path.home()))
    local = Path(os.environ.get("LOCALAPPDATA", Path.home()))
    moves = [(appdata / _OLD_NAME, SETTINGS_DIR),
             (local / _OLD_NAME / "models", local / "Echoglass" / "models")]
    for old, new in moves:
        if old.is_dir() and not new.exists():
            try:
                new.parent.mkdir(parents=True, exist_ok=True)
                os.replace(old, new)          # same drive: instant, even for 3 GB
            except OSError:
                import shutil
                shutil.copytree(old, new, dirs_exist_ok=True)
    try:
        import keyring
        for user, _env in API_KEYS.values():
            if keyring.get_password(KEYRING_SERVICE, user) is None:
                old_key = keyring.get_password(_OLD_NAME, user)
                if old_key:
                    keyring.set_password(KEYRING_SERVICE, user, old_key)
    except Exception:
        pass


def _fill(cls, data: dict):
    """Build dataclass `cls` from `data`, ignoring unknown keys so old files keep loading."""
    names = {f.name for f in dataclasses.fields(cls)}
    return cls(**{k: v for k, v in data.items() if k in names})


def load() -> Config:
    cfg = Config.default()
    if SETTINGS_FILE.exists():
        try:
            data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            cfg = Config(
                asr=_fill(AsrConfig, data.get("asr", {})),
                vad=_fill(VadConfig, data.get("vad", {})),
                translation=_fill(TranslationConfig, data.get("translation", {})),
                overlay=_fill(OverlayConfig, data.get("overlay", {})),
                ui=_fill(UiConfig, data.get("ui", {})),
                api=_fill(ApiConfig, data.get("api", {})),
                screen=_fill(ScreenConfig, data.get("screen", {})),
                device_name=data.get("device_name"),
                music_mode=data.get("music_mode", False),
            )
        except Exception:
            log.exception("Couldn't read %s; using defaults", SETTINGS_FILE)
            cfg = Config.default()
    for field, (user, env) in API_KEYS.items():
        setattr(cfg.translation, field, get_api_key(user) or os.environ.get(env) or None)
    return cfg


def save(cfg: Config) -> None:
    data = dataclasses.asdict(cfg)
    for section, skip in _SKIP.items():
        target = data[section] if section else data
        for k in skip:
            target.pop(k, None)
    SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
    tmp = SETTINGS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(SETTINGS_FILE)


def get_api_key(user: str) -> str | None:
    try:
        import keyring
        return keyring.get_password(KEYRING_SERVICE, user)
    except Exception:
        log.warning("Keyring unavailable; API keys fall back to environment variables")
        return None


def set_api_key(user: str, value: str | None) -> None:
    import keyring
    if value:
        keyring.set_password(KEYRING_SERVICE, user, value)
    else:
        try:
            keyring.delete_password(KEYRING_SERVICE, user)
        except keyring.errors.PasswordDeleteError:
            pass
