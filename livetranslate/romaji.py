"""Romaji (Hepburn) for Japanese text, done locally with cutlet (MIT) + MeCab/fugashi.

The UniDic-lite dictionary MeCab needs is ~250 MB unpacked, so it isn't bundled: the first
time romaji is switched on it's downloaded from PyPI (the official unidic-lite 1.0.8 source
archive, 47 MB, SHA-256 checked) into %LOCALAPPDATA%\\Echoglass\\models\\unidic-lite.
"""

import hashlib
import logging
import os
import re
import tarfile
import threading
import urllib.request
from pathlib import Path
from typing import Callable

log = logging.getLogger(__name__)

URL = ("https://files.pythonhosted.org/packages/55/2b/8cf7514cb57d028abcef625afa847d60ff1ffbf0049c36b78faa7c35046f/"
       "unidic-lite-1.0.8.tar.gz")
SHA256 = "db9d4572d9fdd4d00a97949d4b0741ec480ee05a7e7e2e32f547500dae27b245"
_JAPANESE = re.compile(r"[぀-ヿ一-鿿]")


def _dict_dir() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Echoglass" / "models" / "unidic-lite"


def ensure_dictionary(on_progress: Callable[[int, int], None] | None = None) -> Path:
    d = _dict_dir()
    dicdir = d / "dicdir"
    if (d / ".verified").exists() and (dicdir / "sys.dic").exists():
        return dicdir
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / "unidic-lite.tar.gz.part"
    log.info("Downloading the romaji dictionary (unidic-lite, 47 MB) from PyPI")
    h = hashlib.sha256()
    with urllib.request.urlopen(URL, timeout=30) as r, open(tmp, "wb") as f:
        total, done = int(r.headers.get("Content-Length", 0)), 0
        while chunk := r.read(1 << 20):
            f.write(chunk)
            h.update(chunk)
            done += len(chunk)
            if on_progress:
                on_progress(done, total)
    if h.hexdigest() != SHA256:
        tmp.unlink(missing_ok=True)
        raise RuntimeError("Romaji dictionary failed its checksum")
    prefix = "unidic-lite-1.0.8/unidic_lite/dicdir/"
    with tarfile.open(tmp, "r:gz") as tar:
        for m in tar.getmembers():
            if m.isfile() and m.name.startswith(prefix):
                m.name = m.name[len(prefix):]
                tar.extract(m, dicdir, filter="data")
    tmp.unlink(missing_ok=True)
    (d / ".verified").write_text(SHA256)
    return dicdir


class Romanizer:
    """Thread-safe-enough lazy wrapper: `romaji()` returns None until the dictionary is ready."""

    def __init__(self):
        self._cutlet = None
        self._lock = threading.Lock()
        self.error: str | None = None

    @property
    def ready(self) -> bool:
        return self._cutlet is not None

    def load(self, on_progress: Callable[[int, int], None] | None = None) -> None:
        """Download the dictionary if needed and start MeCab. Call off the UI thread."""
        if self._cutlet is not None:
            return
        try:
            dicdir = ensure_dictionary(on_progress)
            import cutlet
            rc = (dicdir / "mecabrc").as_posix()
            self._cutlet = cutlet.Cutlet(mecab_args=f'-d "{dicdir.as_posix()}" -r "{rc}"')
            self.error = None
        except Exception as e:
            log.exception("Romaji unavailable")
            self.error = str(e)

    def romaji(self, text: str, language: str | None) -> str | None:
        """Romaji for a line Whisper detected as Japanese; None for anything else (Chinese
        shares kanji, so the script alone can't decide)."""
        if self._cutlet is None or language != "ja" or not _JAPANESE.search(text):
            return None
        with self._lock:  # MeCab's tagger isn't safe to share across threads
            try:
                return self._cutlet.romaji(text)
            except Exception:
                return None
