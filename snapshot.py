#!/usr/bin/env python3
"""Snapshot the current proc_music.py into snapshots/YYYY-MM-DD_HH-MM/.

Follows the same nomenclature as the agent backups: timestamped snapshot dirs
(so many per day never overwrite), a "latest/" local-only mirror (gitignored),
and a MANIFEST.json per snapshot. Idempotent-safe: a same-minute second snapshot
gets a -2, -3, ... suffix.

Usage:
    python3 snapshot.py [--note "what changed"]
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import platform
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "proc_music.py"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def script_version(path: Path) -> str | None:
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("VERSION"):
            return line.split("=", 1)[1].strip()
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--note", default="", help="short description of this snapshot")
    args = ap.parse_args()

    if not SRC.is_file():
        raise SystemExit(f"no proc_music.py at {SRC}")

    stamp = dt.datetime.now().strftime("%Y-%m-%d_%H-%M")
    snap_root = ROOT / "snapshots"
    snap = snap_root / stamp
    n = 2
    while snap.exists():  # never overwrite a prior snapshot
        snap = snap_root / f"{stamp}-{n}"
        n += 1
    snap.mkdir(parents=True)

    shutil.copy2(SRC, snap / "proc_music.py")
    manifest = {
        "snapshot": snap.name,
        "created_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "generator": "proc_music.py",
        "version": script_version(SRC),
        "sha256": sha256(snap / "proc_music.py"),
        "python_version": platform.python_version(),
        "note": args.note,
    }
    (snap / "MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    # refresh the local-only mirror (gitignored)
    latest = ROOT / "latest"
    if latest.exists():
        shutil.rmtree(latest)
    shutil.copytree(snap, latest)

    print(snap.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
