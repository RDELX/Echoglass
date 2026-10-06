"""DeepL API backend."""

import deepl

from .base import ContextLine, Translator
from .languages import LANGUAGES


class DeepLTranslator(Translator):
    def __init__(self, api_key: str):
        self.client = deepl.DeepLClient(api_key)
        self.label = "DeepL"

    def translate(self, text: str, source: str | None, target: str,
                  context: list[ContextLine]) -> str:
        src = LANGUAGES.get(source, (None, None, None))[1] if source else None
        tgt = LANGUAGES.get(target, (None, None, None))[2]
        if tgt is None:
            raise ValueError(f"DeepL does not support target language '{target}'")
        result = self.client.translate_text(
            text,
            source_lang=src,
            target_lang=tgt,
            # DeepL uses context to disambiguate but does not translate or bill it.
            context="\n".join(c.source for c in context) or None,
        )
        return result.text
