"""faster-whisper wrapper that turns finished utterances into text."""

import logging
import re
import time
from dataclasses import dataclass
from typing import Callable

import numpy as np

from ..config import AsrConfig
from . import cuda_dlls
from .model_download import ensure_model

cuda_dlls.register()
from faster_whisper import WhisperModel  # noqa: E402

log = logging.getLogger(__name__)

# Phrases Whisper is known to hallucinate on music/silence, learned from YouTube outros
# and subtitle credits in its training data. Matched case-insensitively anywhere in a line.
_HALLUCINATIONS = [
    # Korean
    r"시청해\s*주셔서\s*감사합니다", r"구독과\s*좋아요", r"구독\s*좋아요", r"MBC\s*뉴스",
    # Japanese
    r"ご視聴ありがとうございました", r"チャンネル登録",
    # Chinese
    r"字幕由.*提供", r"请不吝点赞", r"订阅\s*转发", r"字幕\s*by", r"明镜与点点栏目",
    # English
    r"thank(s| you) (so much )?for watching", r"please subscribe", r"amara\.org",
    r"subtitles by", r"like and subscribe",
    # Spanish / Portuguese / French / Italian
    r"gracias por ver", r"suscr[ií]bete", r"obrigad[oa] por assistir",
    r"sous-titres (réalisés|par)", r"merci d'avoir regard", r"grazie per la visione",
    # German / Dutch / Turkish / Russian
    r"untertitel(ung)?\s+(im auftrag|des|von|der)", r"bedankt voor het kijken", r"altyaz[ıi]", r"izledi[gğ]iniz i[cç]in",
    r"продолжение следует", r"субтитры (сделал|подготовил|создавал)", r"спасибо за просмотр",
]
_HALLUCINATION_RE = re.compile("|".join(_HALLUCINATIONS), re.IGNORECASE)

# Whole-line phantoms Whisper emits for instrumental passages. Only dropped in music mode,
# since in normal speech someone may genuinely say them.
_MUSIC_PHANTOMS = {
    "thank you", "thanks", "bye", "bye bye", "bye-bye", "i know", "you", "okay", "oh",
    "감사합니다", "네", "ありがとうございました", "はい", "谢谢", "gracias", "danke",
}


# Below this detection confidence, keep using the last confidently detected language.
_LANG_CONFIDENT = 0.7


@dataclass
class Transcript:
    text: str
    language: str
    start: float          # seconds since capture start
    duration: float       # utterance length in seconds
    asr_seconds: float    # time Whisper took
    uid: int = 0          # utterance id (partials and the final share it)
    final: bool = True    # False = live partial of a sentence still being spoken


class Transcriber:
    def __init__(self, cfg: AsrConfig, on_download: Callable[[float, float], None] | None = None):
        self.cfg = cfg
        path = ensure_model(cfg.model, on_download)
        log.info("Loading Whisper %s on %s (%s)...", cfg.model, cfg.device, cfg.compute_type)
        t0 = time.perf_counter()
        self.model = WhisperModel(path, device=cfg.device, compute_type=cfg.compute_type)
        log.info("Model loaded in %.1fs", time.perf_counter() - t0)
        self._sticky_language: str | None = None

    def warmup(self) -> None:
        """Run one tiny inference so the first real utterance isn't slowed by CUDA init."""
        self.model.transcribe(np.zeros(16000, dtype=np.float32), language=self.cfg.language or "en")

    def _pick_language(self, audio: np.ndarray, update: bool = True) -> str | None:
        """Detect per utterance, but don't let a short or unclear line flip the language."""
        if not update and self._sticky_language:
            return self._sticky_language  # partials: reuse, don't spend a detection pass
        lang, prob, _ = self.model.detect_language(audio)
        if not update:
            # Partials are short: a wrong guess shows nonsense in another language, so
            # only show them once the language is clear.
            return lang if prob >= _LANG_CONFIDENT else None
        if self._sticky_language is None and prob < 0.5:
            return lang  # too unsure to lock in a language yet
        if prob >= _LANG_CONFIDENT or self._sticky_language is None:
            if lang != self._sticky_language:
                log.info("Source language: %s (p=%.2f)", lang, prob)
            self._sticky_language = lang
            return lang
        return self._sticky_language

    def transcribe(self, audio: np.ndarray, start: float, uid: int = 0,
                   final: bool = True) -> Transcript | None:
        """`final=False` is a quick greedy pass for live captions of an unfinished sentence."""
        t0 = time.perf_counter()
        language = self.cfg.language or self._pick_language(audio, update=final)
        if language is None:
            return None
        segments, info = self.model.transcribe(
            audio,
            language=language,
            beam_size=self.cfg.beam_size if final else 1,
            vad_filter=False,                 # we already segmented with Silero
            condition_on_previous_text=False,  # avoids repetition loops across utterances
            without_timestamps=True,
        )
        kept = [
            s.text.strip()
            for s in segments
            if not (s.no_speech_prob > 0.6 and s.avg_logprob < -1.0)
            and s.no_speech_prob <= self.cfg.max_no_speech_prob
        ]
        text = " ".join(t for t in kept if t)
        if not text or _HALLUCINATION_RE.search(text):
            return None
        if self.cfg.drop_music_phantoms and text.strip(" .!?。！？").lower() in _MUSIC_PHANTOMS:
            return None
        return Transcript(
            text=text,
            language=info.language,
            start=start,
            duration=len(audio) / 16000,
            asr_seconds=time.perf_counter() - t0,
            uid=uid,
            final=final,
        )
