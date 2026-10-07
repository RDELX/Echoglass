"""In-app updates from GitHub releases.

Each release (made by packaging/build.ps1) contains:
  - Echoglass-Setup-<ver>.exe + .bin slices   full installer
  - update-from-<old>.zip                          only the files changed since <old>
  - files.json, SHA256SUMS.txt

If there's a delta for the installed version, the app downloads just that (usually a few
MB, since the multi-GB GPU libraries rarely change), quits, and a small PowerShell helper
copies the files over the install and relaunches it. Otherwise it falls back to running
the full installer silently, which also relaunches the app.
"""

import hashlib
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import __version__

log = logging.getLogger(__name__)

RELEASES_REPO = "RDELX/Echoglass"
INNO_APP_ID = "{6F2C1B7A-3E44-4C1B-9D4E-6A1E2B7C9F10}_is1"  # packaging/installer.iss AppId
_UA = {"User-Agent": f"Echoglass/{__version__}", "Accept": "application/vnd.github+json"}


@dataclass
class Release:
    version: str
    notes: str
    url: str                              # release page
    assets: dict[str, tuple[str, int]]    # name -> (download url, size)
    patch: str | None                     # delta zip for this install, if available

    @property
    def files(self) -> list[str]:
        """What we need to download: the delta, or the whole installer."""
        if self.patch:
            return [self.patch, "SHA256SUMS.txt"]
        return [n for n in self.assets if n.startswith("Echoglass-Setup-")] + ["SHA256SUMS.txt"]

    @property
    def size(self) -> int:
        return sum(self.assets[n][1] for n in self.files)


def _ver(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", v)[:3])


def app_dir() -> Path:
    return Path(sys.executable).parent


def can_self_update() -> bool:
    """Only the installed app can replace itself; running from source uses git."""
    return getattr(sys, "frozen", False)


def check(repo: str = RELEASES_REPO, timeout: float = 6) -> Release | None:
    """Return the latest release if it's newer than this build, else None."""
    req = urllib.request.Request(f"https://api.github.com/repos/{repo}/releases/latest", headers=_UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.load(r)
    version = data.get("tag_name", "").lstrip("v")
    if not version or _ver(version) <= _ver(__version__):
        return None
    assets = {a["name"]: (a["browser_download_url"], a["size"]) for a in data.get("assets", [])}
    if "SHA256SUMS.txt" not in assets or not any(n.endswith(".exe") for n in assets):
        log.warning("Release %s is missing the installer or checksums", version)
        return None
    patch = f"update-from-{__version__}.zip"
    if patch not in assets or not (app_dir() / "files.json").exists():
        patch = None  # (deltas are only built when the GPU runtime is unchanged)
    return Release(version, data.get("body") or "", data.get("html_url", ""), assets, patch)


def download(rel: Release, on_progress: Callable[[int, int], None],
             cancelled: Callable[[], bool] = lambda: False) -> Path:
    """Download and verify what the update needs; returns the delta zip or the installer."""
    folder = Path(tempfile.gettempdir()) / "Echoglass-update" / rel.version
    folder.mkdir(parents=True, exist_ok=True)
    total, done = rel.size, 0
    for name in rel.files:
        url, size = rel.assets[name]
        dest = folder / name
        if dest.exists() and dest.stat().st_size == size:
            done += size
            on_progress(done, total)
            continue
        part = folder / (name + ".part")
        req = urllib.request.Request(url, headers={"User-Agent": _UA["User-Agent"]})
        with urllib.request.urlopen(req, timeout=30) as r, open(part, "wb") as f:
            while chunk := r.read(1 << 20):
                if cancelled():
                    raise RuntimeError("Update cancelled")
                f.write(chunk)
                done += len(chunk)
                on_progress(done, total)
        part.replace(dest)

    expected = {}
    for line in (folder / "SHA256SUMS.txt").read_text(encoding="utf-8-sig").splitlines():
        parts = line.replace("*", " ").split()
        if len(parts) == 2:
            expected[parts[1]] = parts[0].lower()
    for name in rel.files:
        if name == "SHA256SUMS.txt":
            continue
        h = hashlib.sha256()
        with open(folder / name, "rb") as f:
            while chunk := f.read(1 << 22):
                h.update(chunk)
        if expected.get(name) != h.hexdigest():
            (folder / name).unlink(missing_ok=True)
            raise RuntimeError(f"Checksum mismatch for {name}; please try again")
    if rel.patch:
        return folder / rel.patch
    return next(folder / n for n in rel.files if n.endswith(".exe"))


# Runs after the app has quit: copy the delta over the install, update the version shown
# in "Installed apps", relaunch. On failure it runs the full installer if it's there.
_APPLY_PS1 = r'''
param([int]$AppPid, [string]$Zip, [string]$App, [string]$Version, [string]$Log)
$ErrorActionPreference = "Stop"
Start-Transcript -Path $Log -Force | Out-Null
try {
    Wait-Process -Id $AppPid -Timeout 60 -ErrorAction SilentlyContinue
    $tmp = Join-Path ([IO.Path]::GetDirectoryName($Zip)) "extracted"
    if (Test-Path $tmp) { Remove-Item $tmp -Recurse -Force }
    Expand-Archive -Path $Zip -DestinationPath $tmp -Force
    $removed = Get-Content (Join-Path $tmp "_removed.txt") -ErrorAction SilentlyContinue
    foreach ($f in $removed) { if ($f) { Remove-Item (Join-Path $App $f) -Force -ErrorAction SilentlyContinue } }
    for ($i = 0; $i -lt 10; $i++) {
        try { Copy-Item (Join-Path $tmp "files\*") $App -Recurse -Force; break }
        catch { if ($i -eq 9) { throw }; Start-Sleep -Seconds 1 }   # files still locked
    }
    $key = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\__APPID__"
    if (Test-Path $key) { Set-ItemProperty $key -Name DisplayVersion -Value $Version }
    Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
    Write-Output "Updated to $Version"
} catch {
    Write-Output "Partial update failed: $_"
}
Start-Process (Join-Path $App "Echoglass.exe")
Stop-Transcript | Out-Null
'''


def install(path: Path, version: str) -> None:
    """Start applying the update; the caller must quit right after."""
    if path.suffix == ".zip":
        script = path.parent / "apply-update.ps1"
        script.write_text(_APPLY_PS1.replace("__APPID__", INNO_APP_ID), encoding="utf-8")
        log.info("Applying partial update %s", path)
        subprocess.Popen(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden",
             "-File", str(script), "-AppPid", str(os.getpid()), "-Zip", str(path),
             "-App", str(app_dir()), "-Version", version, "-Log", str(path.parent / "update.log")],
            # PowerShell needs a (hidden) console: with DETACHED_PROCESS it exits without running.
            close_fds=True,
            creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP)
        return
    log.info("Starting installer %s", path)
    subprocess.Popen([str(path), "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS",
                      f"/LOG={path.parent / 'install.log'}"],
                     cwd=path.parent, close_fds=True, creationflags=subprocess.DETACHED_PROCESS)
