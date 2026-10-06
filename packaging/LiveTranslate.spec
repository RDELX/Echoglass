# PyInstaller spec: builds dist\LiveTranslate\LiveTranslate.exe (one-folder, windowed).
# Run via packaging\build.ps1, not directly.

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_dynamic_libs

ROOT = SPECPATH + "\\.."

datas, binaries, hiddenimports = [], [], []
for pkg in ("faster_whisper", "ctranslate2", "pysilero_vad", "demucs", "pyaudiowpatch", "soxr"):
    d, b, h = collect_all(pkg)
    datas += d; binaries += b; hiddenimports += h

# PyTorch/torchaudio are NOT bundled: the installer downloads the official wheels from
# download.pytorch.org into _internal\ (see make_deps.py), where the onedir app imports them
# from disk. Their pure-Python dependencies are bundled here instead.
for pkg in ("sympy", "mpmath", "networkx", "jinja2", "markupsafe", "filelock", "fsspec",
            "typing_extensions", "julius", "einops", "openunmix", "yaml"):
    try:
        d, b, h = collect_all(pkg)
        datas += d; binaries += b; hiddenimports += h
    except Exception:
        pass

# PyTorch imports many standard-library modules our own code never touches (e.g.
# pickletools). Since it isn't analysed at build time, bundle the whole stdlib.
import sys
from PyInstaller.utils.hooks import collect_submodules
_SKIP = {"tkinter", "turtle", "turtledemo", "idlelib", "test", "lib2to3", "ensurepip", "venv",
         "pydoc_data", "this", "antigravity"}
for mod in sorted(sys.stdlib_module_names - _SKIP):
    if mod.startswith("_"):
        continue
    try:
        hiddenimports += collect_submodules(mod, filter=lambda n: ".test" not in n)
    except Exception:
        hiddenimports.append(mod)

datas += [(ROOT + "\\livetranslate\\ui\\assets", "livetranslate\\ui\\assets")]
hiddenimports += ["keyring.backends.Windows", "livetranslate.audio.separator",
                  "livetranslate.translation.openai_compat", "livetranslate.translation.deepl_backend",
                  "livetranslate.translation.claude_backend"]

a = Analysis(
    [ROOT + "\\run_app.py"],
    pathex=[ROOT],
    datas=datas,
    binaries=binaries,
    hiddenimports=hiddenimports,
    # CTranslate2 uses PyTorch's cuBLAS/cuDNN in the packaged app (see asr/cuda_dlls.py),
    # so the separate nvidia-* wheels would only duplicate ~1.3 GB.
    excludes=["torch", "torchaudio", "functorch", "torchgen", "nvidia",
              "tkinter", "matplotlib", "IPython", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="LiveTranslate",
    console=False,
    icon=ROOT + "\\packaging\\icon.ico",
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="LiveTranslate", upx=False)
