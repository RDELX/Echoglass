# PyInstaller spec: builds dist\LiveTranslate\LiveTranslate.exe (one-folder, windowed).
# Run via packaging\build.ps1, not directly.

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_dynamic_libs

ROOT = SPECPATH + "\\.."

datas, binaries, hiddenimports = [], [], []
for pkg in ("faster_whisper", "ctranslate2", "pysilero_vad", "demucs", "pyaudiowpatch", "soxr"):
    d, b, h = collect_all(pkg)
    datas += d; binaries += b; hiddenimports += h

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
    excludes=["nvidia", "tkinter", "matplotlib", "IPython", "pytest"],
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
