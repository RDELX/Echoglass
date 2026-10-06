"""Swappable translation backends. Use `create_translator(cfg)` to build one from settings."""

import os

from ..config import TranslationConfig
from .base import ContextLine, Translator
from .worker import Translated, TranslationWorker

BACKENDS = ["ollama", "lmstudio", "openai", "deepl", "claude", "none"]


def create_translator(cfg: TranslationConfig) -> Translator | None:
    b = cfg.backend
    if b == "none":
        return None
    if b == "ollama":
        from .openai_compat import OpenAICompatTranslator
        return OpenAICompatTranslator(cfg.ollama_url, cfg.ollama_model, label="Ollama",
                                      reasoning_effort="none")
    if b == "lmstudio":
        from .openai_compat import OpenAICompatTranslator
        return OpenAICompatTranslator(cfg.lmstudio_url, cfg.lmstudio_model or "local-model",
                                      label="LM Studio", reasoning_effort="none")
    if b == "openai":
        from .openai_compat import OpenAICompatTranslator
        key = cfg.openai_api_key or os.environ.get("OPENAI_API_KEY")
        if not key:
            raise ValueError("OpenAI backend needs an API key (OPENAI_API_KEY)")
        return OpenAICompatTranslator(None, cfg.openai_model, api_key=key, label="OpenAI")
    if b == "deepl":
        from .deepl_backend import DeepLTranslator
        key = cfg.deepl_api_key or os.environ.get("DEEPL_API_KEY")
        if not key:
            raise ValueError("DeepL backend needs an API key (DEEPL_API_KEY)")
        return DeepLTranslator(key)
    if b == "claude":
        from .claude_backend import ClaudeTranslator
        return ClaudeTranslator(cfg.anthropic_api_key, cfg.claude_model, cfg.claude_effort)
    raise ValueError(f"Unknown translation backend '{b}'. Choose from: {', '.join(BACKENDS)}")


__all__ = ["BACKENDS", "ContextLine", "Translated", "Translator", "TranslationWorker",
           "create_translator"]
