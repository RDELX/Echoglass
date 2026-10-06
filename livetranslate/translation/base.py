"""The interface every translation backend implements."""

from abc import ABC, abstractmethod
from dataclasses import dataclass

from .languages import name


@dataclass
class ContextLine:
    source: str
    translation: str


class Translator(ABC):
    """Translates one utterance at a time.

    `context` holds the most recent (source, translation) pairs so backends that can use
    it (LLMs, DeepL) keep names, pronouns and tone consistent across lines.
    """

    label: str = "translator"

    @abstractmethod
    def translate(self, text: str, source: str | None, target: str,
                  context: list[ContextLine]) -> str: ...


def llm_prompt(text: str, source: str | None, target: str,
               context: list[ContextLine]) -> tuple[str, str]:
    """Shared (system, user) prompt for the LLM backends."""
    src = name(source) if source else "the source language"
    system = (
        f"You translate live speech-recognition transcripts from {src} into {name(target)} "
        "for on-screen subtitles. The transcript may contain recognition errors or be cut "
        "mid-sentence; translate what was most likely said, naturally and concisely. "
        "Reply with the translation only: no quotes, notes, romanization or explanations."
    )
    parts = []
    if context:
        lines = "\n".join(f"{c.source}\n→ {c.translation}" for c in context)
        parts.append(f"Previous lines, for context only (do not translate again):\n{lines}\n")
    parts.append(f"Translate this line:\n{text}")
    return system, "\n".join(parts)
