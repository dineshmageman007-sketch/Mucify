# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 mageman007 and contributors
"""
Where Mucify keeps things.

* Bundled, read-only resources (templates, static files, sldl.exe, rsgain.exe)
  live next to the program (PyInstaller's bundle dir when frozen, the repo
  root when running from source).
* Everything the user generates (config, library, CSVs, logs, staged tools)
  lives under  %APPDATA%\\Mucify  (override with the MUCIFY_HOME env var).
* The default music library is  <Windows Music folder>\\Mucify.
"""
import os
import shutil
import sys
from pathlib import Path

from . import __version__

APP_NAME = "Mucify"
FROZEN = bool(getattr(sys, "frozen", False))


# ---------------------------------------------------------------- bundle
def bundle_root() -> Path:
    """Folder that contains  mucify/templates, mucify/static  and  tools/ ."""
    if FROZEN:
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return Path(__file__).resolve().parent.parent


def templates_dir() -> Path:
    return bundle_root() / "mucify" / "templates"


def static_dir() -> Path:
    return bundle_root() / "mucify" / "static"


def bundled_tool_dir(name: str) -> Path:
    return bundle_root() / "tools" / name


# ---------------------------------------------------------------- user dirs
def user_data_dir() -> Path:
    override = os.environ.get("MUCIFY_HOME")
    if override:
        base = Path(override)
    elif os.name == "nt":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming") / APP_NAME
    else:  # only used for development / tests on non-Windows machines
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / APP_NAME
    base.mkdir(parents=True, exist_ok=True)
    return base


def config_path() -> Path:
    return user_data_dir() / "config.json"


def data_dir() -> Path:
    p = user_data_dir() / "data"
    p.mkdir(parents=True, exist_ok=True)
    return p


def uploads_dir() -> Path:
    p = data_dir() / "uploads"
    p.mkdir(parents=True, exist_ok=True)
    return p


def logs_dir() -> Path:
    p = user_data_dir() / "logs"
    p.mkdir(parents=True, exist_ok=True)
    return p


def webview_storage_dir() -> Path:
    """Browser profile (cookies / localStorage) so Qobuz login survives restarts."""
    p = user_data_dir() / "webview"
    p.mkdir(parents=True, exist_ok=True)
    return p


def default_working_dir() -> Path:
    return user_data_dir() / "Working"


def windows_music_dir() -> Path:
    """The user's real Music folder (follows OneDrive / redirected folders)."""
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes

            class GUID(ctypes.Structure):
                _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                            ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]

            # FOLDERID_Music = {4BD8D571-6D19-48D3-BE97-422220080E43}
            guid = GUID(0x4BD8D571, 0x6D19, 0x48D3,
                        (ctypes.c_ubyte * 8)(0xBE, 0x97, 0x42, 0x22, 0x20, 0x08, 0x0E, 0x43))
            out = ctypes.c_wchar_p()
            res = ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(guid), 0, None, ctypes.byref(out))
            if res == 0 and out.value:
                path = Path(out.value)
                ctypes.windll.ole32.CoTaskMemFree(out)
                return path
        except Exception:
            pass
    return Path.home() / "Music"


def default_music_dir() -> Path:
    return windows_music_dir() / APP_NAME


def ensure_default_folders():
    """Create the default folders (idempotent). Returns (music, working)."""
    music, working = default_music_dir(), default_working_dir()
    for p in (music, working):
        p.mkdir(parents=True, exist_ok=True)
    return music, working


# ---------------------------------------------------------------- tools
def _staged_sldl_dir() -> Path:
    return user_data_dir() / "tools" / "sldl"


def stage_sldl() -> Path:
    """
    sldl reads its credentials from an sldl.conf that sits NEXT TO sldl.exe,
    and the install folder may not be writable. So the bundled (tested,
    never-auto-updated) sldl.exe is copied once into  %APPDATA%\\Mucify\\tools\\sldl
    and run from there. Re-copied only when the app version or exe size changes.
    Returns the path to the exe that should be executed (staged copy, or the
    bundled one if staging fails).
    """
    src_dir = bundled_tool_dir("sldl")
    src = src_dir / "sldl.exe"
    if not src.exists():
        return src
    dst_dir = _staged_sldl_dir()
    dst = dst_dir / "sldl.exe"
    marker = dst_dir / ".staged"
    stamp = f"{__version__}:{src.stat().st_size}"
    try:
        dst_dir.mkdir(parents=True, exist_ok=True)
        if not (dst.exists() and marker.exists() and marker.read_text().strip() == stamp):
            tmp = dst_dir / "sldl.exe.new"
            shutil.copy2(src, tmp)
            os.replace(tmp, dst)
            lic = src_dir / "LICENSE.txt"
            if lic.exists():
                shutil.copy2(lic, dst_dir / "LICENSE.txt")
            marker.write_text(stamp)
        return dst
    except Exception:
        return src


def bundled_rsgain() -> Path:
    return bundled_tool_dir("rsgain") / "rsgain.exe"


def resolve_tool(manual_override: str, filename: str):
    """Return the path of sldl.exe / rsgain.exe, or None.
    A manual override (Settings > Advanced) wins if it still exists; otherwise
    the bundled, tested copy is used. Nothing is ever downloaded."""
    manual = (manual_override or "").strip()
    if manual and os.path.exists(manual):
        return manual
    name = filename.lower()
    if name == "sldl.exe":
        p = stage_sldl()
    elif name == "rsgain.exe":
        p = bundled_rsgain()
    else:
        return None
    return str(p) if p.exists() else None


# ---------------------------------------------------------------- legal documents
LEGAL_DOCS = {            # id -> (title, relative path inside the legal folder / repo)
    "license": ("License (GPL-3.0-or-later)", "LICENSE"),
    "third_party": ("Third-party components", "THIRD_PARTY.md"),
    "disclaimer": ("Disclaimer", "DISCLAIMER.md"),
    "privacy": ("Privacy", "PRIVACY.md"),
    "credits": ("Credits", "CREDITS.md"),
}
TOOL_LICENSES = {         # id -> (title, tool folder, file)
    "sldl_license": ("sldl licence (AGPL-3.0)", "sldl", "LICENSE.txt"),
    "rsgain_license": ("rsgain licence (BSD-2-Clause)", "rsgain", "LICENSE.txt"),
}


def legal_file(doc_id: str):
    """Path of a legal document (bundled in 'legal' when packaged, repo root in development)."""
    if doc_id in LEGAL_DOCS:
        rel = LEGAL_DOCS[doc_id][1]
        return (bundle_root() / "legal" / rel) if FROZEN else (bundle_root() / rel)
    if doc_id in TOOL_LICENSES:
        _title, tool, fname = TOOL_LICENSES[doc_id]
        return bundled_tool_dir(tool) / fname
    return None


def legal_title(doc_id: str) -> str:
    return (LEGAL_DOCS.get(doc_id) or TOOL_LICENSES.get(doc_id) or ("", ))[0]
