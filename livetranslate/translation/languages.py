"""Language codes (Whisper ISO-639-1) with display names and DeepL codes."""

# code: (English name, DeepL source code, DeepL target code)
LANGUAGES: dict[str, tuple[str, str | None, str | None]] = {
    "ko": ("Korean", "KO", "KO"),
    "en": ("English", "EN", "EN-US"),
    "ja": ("Japanese", "JA", "JA"),
    "zh": ("Chinese", "ZH", "ZH-HANS"),
    "es": ("Spanish", "ES", "ES"),
    "fr": ("French", "FR", "FR"),
    "de": ("German", "DE", "DE"),
    "it": ("Italian", "IT", "IT"),
    "pt": ("Portuguese", "PT", "PT-BR"),
    "ru": ("Russian", "RU", "RU"),
    "tr": ("Turkish", "TR", "TR"),
    "nl": ("Dutch", "NL", "NL"),
    "pl": ("Polish", "PL", "PL"),
    "uk": ("Ukrainian", "UK", "UK"),
    "id": ("Indonesian", "ID", "ID"),
    "vi": ("Vietnamese", None, None),
    "th": ("Thai", None, None),
    "ar": ("Arabic", "AR", "AR"),
    "hi": ("Hindi", None, None),
}


def name(code: str) -> str:
    return LANGUAGES.get(code, (code,))[0]
