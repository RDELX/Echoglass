"""Text detection + recognition for screen regions (RapidOCR, ONNX on CPU).

The PP-OCRv6 multilingual recognizer that ships with RapidOCR reads Latin, Japanese and
Chinese well but not Hangul. Lines it clearly failed on (far too few characters for the
width of the box) are re-read with the Korean recognizer, which RapidOCR downloads from
its official model hub the first time it's needed.
"""

import logging
import re
from dataclasses import dataclass

import numpy as np

log = logging.getLogger(__name__)

_HANGUL = re.compile(r"[가-힣ㄱ-ㆎ]")


@dataclass
class OcrLine:
    text: str
    x: int          # box in image pixels
    y: int
    w: int
    h: int
    score: float


class ScreenOCR:
    def __init__(self):
        from rapidocr import RapidOCR
        self._engine = RapidOCR(params={"Global.log_level": "warning"})
        self._korean = None

    def _korean_engine(self):
        if self._korean is None:
            from rapidocr import LangRec, ModelType, OCRVersion, RapidOCR
            self._korean = RapidOCR(params={"Global.log_level": "warning",
                                            "Rec.lang_type": LangRec.KOREAN,
                                            "Rec.ocr_version": OCRVersion.PPOCRV5,
                                            "Rec.model_type": ModelType.MOBILE})
        return self._korean

    def read(self, img_bgr: np.ndarray) -> list[OcrLine]:
        res = self._engine(img_bgr)
        if res.boxes is None:
            return []
        lines = []
        for text, score, box in zip(res.txts, res.scores, res.boxes):
            xs, ys = box[:, 0], box[:, 1]
            x, y = int(xs.min()), int(ys.min())
            w, h = int(xs.max() - x), int(ys.max() - y)
            if w < 4 or h < 4:
                continue
            text, score = self._maybe_korean(img_bgr, text, float(score), x, y, w, h)
            if text.strip():
                lines.append(OcrLine(text.strip(), x, y, w, h, score))
        lines.sort(key=lambda l: (l.y, l.x))
        return lines

    def _maybe_korean(self, img, text, score, x, y, w, h):
        # A real line of text has roughly one character per ~0.9 line-heights of width.
        expected = w / max(h * 0.9, 1)
        if len(text) >= expected * 0.45 and score >= 0.8:
            return text, score
        crop = img[max(0, y - 2):y + h + 2, max(0, x - 2):x + w + 2]
        try:
            r = self._korean_engine()(crop, use_det=False, use_cls=False, use_rec=True)
        except Exception as e:
            log.warning("Korean OCR unavailable: %s", e)
            return text, score
        if r.txts and _HANGUL.search(r.txts[0]) and len(r.txts[0]) > len(text):
            return r.txts[0], float(r.scores[0])
        return text, score
