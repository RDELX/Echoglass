"""In-app updates from GitHub releases.

A release must contain the Inno Setup installer (`LiveTranslate-Setup-<ver>.exe`), its
`.bin` slices and `SHA256SUMS.txt` (packaging/build.ps1 produces all of them). Updating
downloads everything, verifies the checksums, runs the installer silently and quits;
the installer relaunches the app when it's done.
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

# Public repo the app checks for releases (the code repo itself is private).
RELEASES_REPO = "RDELX/LiveTranslate-releases"
_UA = {"User-Agent": f"LiveTranslate/{__version__}", "Accept": "application/vnd.github+json"}


@dataclass
class Release:
    version: str
    notes: str
    url: str                      # release page
    assets: dict[str, tuple[str, int]]  # name -> (download url, size)

    @property
    def size(self) -> int:
        return sum(s for _, s in self.assets.values())


def _ver(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", v)[:3])


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
    if not any(n.endswith(".exe") for n in assets) or "SHA256SUMS.txt" not in assets:
        log.warning("Release %s is missing the installer or checksums", version)
        return None
    return Release(version, data.get("body") or "", data.get("html_url", ""), assets)


def download(rel: Release, on_progress: Callable[[int, int], None],
             cancelled: Callable[[], bool] = lambda: False) -> Path:
    """Download and verify all release files; returns the installer path."""
    folder = Path(tempfile.gettempdir()) / "LiveTranslate-update" / rel.version
    folder.mkdir(parents=True, exist_ok=True)
    total, done = rel.size, 0
    for name, (url, size) in rel.assets.items():
        dest = folder / name
        if dest.exists() and dest.stat().st_size == size:
            done += size
            on_progress(done, total)
            continue
        req = urllib.request.Request(url, headers={"User-Agent": _UA["User-Agent"]})
        with urllib.request.urlopen(req, timeout=30) as r, open(dest.with_suffix(".part"), "wb") as f:
            while chunk := r.read(1 << 20):
                if cancelled():
                    raise RuntimeError("Update cancelled")
                f.write(chunk)
                done += len(chunk)
                on_progress(done, total)
        dest.with_suffix(".part").replace(dest)

    expected = {}
    for line in (folder / "SHA256SUMS.txt").read_text(encoding="utf-8-sig").splitlines():
        parts = line.replace("*", " ").split()
        if len(parts) == 2:
            expected[parts[1]] = parts[0].lower()
    for name in rel.assets:
        if name == "SHA256SUMS.txt":
            continue
        h = hashlib.sha256()
        with open(folder / name, "rb") as f:
            while chunk := f.read(1 << 22):
                h.update(chunk)
        if expected.get(name) != h.hexdigest():
            (folder / name).unlink(missing_ok=True)
            raise RuntimeError(f"Checksum mismatch for {name}; please try again")
    return next(folder / n for n in rel.assets if n.endswith(".exe"))


def install(installer: Path) -> None:
    """Start the silent install; the caller should quit right after."""
    log.info("Starting installer %s", installer)
    subprocess.Popen([str(installer), "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
                      "/CLOSEAPPLICATIONS", f"/LOG={installer.parent / 'install.log'}"],
                     cwd=installer.parent, close_fds=True,
                     creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))
