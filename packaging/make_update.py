"""Build-time helper for partial (delta) updates. Called by build.ps1.

    python make_update.py manifest <app_dir> <version> <runtime_id>
        Writes <app_dir>/files.json: every file's SHA-256 (the GPU runtime has already been
        moved out by make_runtime.py) and the runtime id, so a later build can tell which
        files changed and the updater can tell whether the runtime changed.

    python make_update.py delta <app_dir> <old_files.json> <out_zip>
        Zips only the files that differ from the old manifest (plus the new files.json and
        a list of files to delete). The in-app updater applies it over an existing install.
"""

import hashlib
import json
import sys
import zipfile
from pathlib import Path

MANIFEST = "files.json"


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        while chunk := f.read(1 << 22):
            h.update(chunk)
    return h.hexdigest()


def manifest(app: Path, version: str, runtime: str) -> None:
    files = {p.relative_to(app).as_posix(): sha256(p)
             for p in sorted(app.rglob("*")) if p.is_file() and p.name != MANIFEST}
    (app / MANIFEST).write_text(json.dumps({"version": version, "runtime": runtime, "files": files},
                                           indent=0), encoding="utf-8")
    print(f"{MANIFEST}: {len(files)} files")


def delta(app: Path, old_manifest: Path, out: Path) -> None:
    old = json.loads(old_manifest.read_text(encoding="utf-8"))
    new = json.loads((app / MANIFEST).read_text(encoding="utf-8"))
    exes = lambda m: {f for f in m["files"] if "/" not in f and f.endswith(".exe")}
    if exes(old) != exes(new):
        print(f"skip delta from {old['version']}: the app was renamed (needs the full installer)")
        return
    if old.get("runtime") != new.get("runtime"):
        print(f"skip delta from {old['version']}: GPU runtime changed (needs the full installer)")
        return
    changed = [f for f, h in new["files"].items() if old["files"].get(f) != h]
    removed = [f for f in old["files"] if f not in new["files"]]
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for f in changed:
            z.write(app / f, f"files/{f}")
        z.write(app / MANIFEST, f"files/{MANIFEST}")
        z.writestr("_removed.txt", "\n".join(removed))
        z.writestr("_version.txt", new["version"])
    size = sum((app / f).stat().st_size for f in changed)
    print(f"{out.name}: {len(changed)} changed ({size / 1e6:.1f} MB raw), {len(removed)} removed, "
          f"zip {out.stat().st_size / 1e6:.1f} MB (from {old['version']})")


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "manifest":
        manifest(Path(sys.argv[2]), sys.argv[3], sys.argv[4])
    elif cmd == "delta":
        delta(Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4]))
    else:
        sys.exit(__doc__)
