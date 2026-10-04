# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 mageman007 and contributors
r"""
Per-playlist folders and the "last processed file" memory.

Every playlist gets its own folder inside the working folder:

    <working folder>\<Playlist name>\
        1_to_download.csv   what still needs downloading (after the Playlist Manager)
        2_enriched.csv      the same tracks with Qobuz quality info
        3_skipped.csv       everything that did NOT get downloaded
        4_successful.csv    everything that DID get downloaded

The playlist name comes from the CSV the user feeds in. Later stages recognise
files that already live in a playlist folder and keep using that folder.
"""
import csv
import json
import os
import re
import threading
from datetime import datetime
from pathlib import Path

STAGE_FILES = {
    "to_download": "1_to_download.csv",
    "enriched": "2_enriched.csv",
    "skipped": "3_skipped.csv",
    "successful": "4_successful.csv",
}

_BAD_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_TS_PREFIX = re.compile(r"^\d{8}_\d{6}_")
_GENERATED = re.compile(r"^(playlist_enriched|to_download|already_have)_\d{8}_\d{6}$", re.I)
_STAGE_PREFIX = re.compile(r"^[1-4]_")
_GENERIC_STEMS = {"", "to_download", "enriched", "skipped", "successful", "download_report"}
_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}


def slug(name: str, fallback: str = "Playlist") -> str:
    """Make a string safe to use as a Windows folder name."""
    s = _BAD_CHARS.sub(" ", name or "")
    s = re.sub(r"\s+", " ", s).strip(" .")
    s = s[:80].strip(" .")
    if not s or s.lower() in _RESERVED:
        return fallback
    return s


def playlist_name_from_path(path) -> str:
    stem = Path(str(path)).stem
    stem = _TS_PREFIX.sub("", stem)                 # uploads get a timestamp prefix
    if _GENERATED.match(stem):
        return slug("", f"Playlist {datetime.now():%Y-%m-%d %H%M}")
    stem = _STAGE_PREFIX.sub("", stem)
    if stem.lower() in _GENERIC_STEMS:
        return slug("", f"Playlist {datetime.now():%Y-%m-%d %H%M}")
    return slug(stem)


def folder_for_input(working_dir, input_path) -> Path:
    """The playlist folder a given input file belongs to (not created)."""
    wd = Path(working_dir)
    p = Path(str(input_path))
    try:
        parent = p.resolve().parent
        if parent.parent == wd.resolve() and _STAGE_PREFIX.match(p.name):
            return parent                           # already inside a playlist folder
    except OSError:
        pass
    return wd / playlist_name_from_path(p)


def stage_path(folder, key) -> Path:
    return Path(folder) / STAGE_FILES[key]


# ------------------------------------------------------------ recent store
_lock = threading.Lock()


def _load(store: Path) -> dict:
    try:
        with open(store, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def remember(store: Path, key: str, path, name: str = "", count=None):
    """Record the most recent output of a stage (what the next stage will probably use)."""
    with _lock:
        data = _load(store)
        data[key] = {"path": str(path), "name": name, "count": count,
                     "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
        tmp = Path(str(store) + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, store)


def recent(store: Path) -> dict:
    """Recorded entries whose file/folder still exists."""
    with _lock:
        data = _load(store)
    return {k: v for k, v in data.items() if isinstance(v, dict) and v.get("path") and os.path.exists(v["path"])}


# ------------------------------------------------------------ csv helpers
def write_rows(path, fieldnames, rows):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def merge_successful(path, new_rows, fieldnames):
    """Keep tracks that were already downloaded in earlier runs of the same playlist
    (used when the user re-runs only the skipped list). Returns (fieldnames, rows)."""
    old_rows, old_fields = [], []
    try:
        with open(path, newline="", encoding="utf-8-sig") as f:
            r = csv.DictReader(f)
            old_fields = list(r.fieldnames or [])
            old_rows = list(r)
    except OSError:
        pass
    fields = list(fieldnames) + [c for c in old_fields if c not in fieldnames]
    seen, merged = set(), []
    for row in new_rows + old_rows:
        key = ((row.get("title") or "").strip().lower(), (row.get("artist") or "").strip().lower())
        if key in seen:
            continue
        seen.add(key)
        merged.append(row)
    return fields, merged
