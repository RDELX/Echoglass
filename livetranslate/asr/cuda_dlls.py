"""Make the pip-installed CUDA 12 / cuDNN 9 DLLs visible to CTranslate2 on Windows.

The nvidia-* wheels put their DLLs under site-packages/nvidia/<lib>/bin, which is not
on the DLL search path. CTranslate2 loads some of them lazily with LoadLibrary, so we
both register the directories and prepend them to PATH. Must run before importing
faster_whisper.
"""

import os
import sys
from pathlib import Path

_done = False


def register() -> None:
    global _done
    if _done or sys.platform != "win32":
        return
    _done = True
    dirs: list[Path] = []
    # The packaged app ships PyTorch's copies of cuBLAS/cuDNN (same CUDA 12 / cuDNN 9
    # major versions CTranslate2 needs) instead of duplicating the nvidia-* wheels.
    base = Path(getattr(sys, "_MEIPASS", ""))
    if getattr(sys, "frozen", False):
        dirs += [base / "torch" / "lib", *base.glob("nvidia/*/bin")]
    else:
        try:
            import nvidia  # namespace package from the nvidia-* wheels
            for root in map(Path, nvidia.__path__):
                dirs += list(root.glob("*/bin"))
        except ImportError:
            pass
    for d in dirs:
        if d.is_dir():
            os.add_dll_directory(str(d))
            os.environ["PATH"] = str(d) + os.pathsep + os.environ.get("PATH", "")
