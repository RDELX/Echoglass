"""Fetch Whisper models from Hugging Face with progress, so first launch isn't a silent wait."""

import logging
from typing import Callable

import huggingface_hub
from faster_whisper.utils import _MODELS
from tqdm.auto import tqdm

log = logging.getLogger(__name__)

# Same file set faster_whisper.download_model fetches.
_ALLOW = ["config.json", "preprocessor_config.json", "model.bin", "tokenizer.json", "vocabulary.*"]


def ensure_model(size_or_id: str, on_progress: Callable[[float, float], None] | None = None) -> str:
    """Return a local path to the model, downloading it first if needed.

    `on_progress(done_bytes, total_bytes)` is called during a download.
    """
    repo = size_or_id if "/" in size_or_id else _MODELS.get(size_or_id, size_or_id)
    try:
        return huggingface_hub.snapshot_download(repo, allow_patterns=_ALLOW, local_files_only=True)
    except Exception:
        pass
    log.info("Downloading Whisper model %s", repo)

    class _Progress(tqdm):
        def __init__(self, *a, **kw):
            kw["disable"] = False
            super().__init__(*a, **kw)

        def update(self, n=1):
            super().update(n)
            # snapshot_download reports bytes on the bar with unit "B"
            if on_progress and self.unit == "B" and self.total:
                on_progress(self.n, self.total)

    return huggingface_hub.snapshot_download(repo, allow_patterns=_ALLOW, tqdm_class=_Progress)
