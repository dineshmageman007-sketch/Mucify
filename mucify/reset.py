# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 mageman007 and contributors
r"""
Reset / uninstall: remove everything Mucify stored on this PC.

What is removed
  * always   %APPDATA%\Mucify  (settings, Soulseek/Qobuz logins, library index, logs,
             the app's browser profile, the staged sldl copy, the default Working folder)
  * optional the playlist folders (1_to_download ... 4_successful) inside a *custom* working folder
  * optional the default music library  <Music>\Mucify   (never any other music folder)
  * uninstall only: the Windows uninstaller is started afterwards to remove the program itself.

Mucify can't delete files that its own window is still using, so the work is done by a tiny
helper process (`Mucify.exe --apply-wipe <plan.json>`): the app starts it, quits, and the helper
waits for the app to exit, deletes the folders and then restarts Mucify (reset) or starts the
uninstaller (uninstall).

Safety: only folders on a strict allow-list are ever deleted (Mucify's own data folder, the
default Music\Mucify folder, and playlist folders that contain nothing but Mucify's four CSV
files). The helper re-checks every path before touching it.
"""
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from . import paths, projects

DETACHED = 0x00000008 | 0x00000200      # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP


# ----------------------------------------------------------------- safety
def _protected_folders() -> set:
    home = Path.home()
    names = ["Documents", "Desktop", "Downloads", "Music", "Pictures", "Videos",
             "AppData", "AppData/Roaming", "AppData/Local"]
    out = {home.resolve()} | {(home / n).resolve() for n in names}
    out.add(paths.windows_music_dir().resolve())
    return out


def _is_protected(p: Path) -> bool:
    p = p.resolve()
    return p == Path(p.anchor) or len(p.parts) < 3 or p in _protected_folders()


def is_inside(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except (ValueError, OSError):
        return False


def is_app_folder(p: Path) -> bool:
    return p.resolve() == paths.user_data_dir().resolve() and not _is_protected(p)


def is_default_music(p: Path) -> bool:
    return p.resolve() == paths.default_music_dir().resolve() and not _is_protected(p)


def is_stage_only(p: Path) -> bool:
    """A playlist folder created by Mucify: only 1_/2_/3_/4_ CSV files, nothing else."""
    if not p.is_dir() or _is_protected(p):
        return False
    allowed = set(projects.STAGE_FILES.values())
    items = list(p.rglob("*"))
    return bool(items) and all(f.is_file() and f.name in allowed for f in items)


def target_allowed(p: Path) -> bool:
    return is_app_folder(p) or is_default_music(p) or is_stage_only(p)


def playlist_folders(working: Path) -> list:
    if not working.is_dir():
        return []
    return [d for d in sorted(working.iterdir()) if d.is_dir() and is_stage_only(d)]


# ----------------------------------------------------------------- preview / plan
def dir_stats(p: Path):
    size = files = 0
    for root, _dirs, names in os.walk(p):
        for n in names:
            try:
                size += os.path.getsize(os.path.join(root, n))
                files += 1
            except OSError:
                pass
    return size, files


def uninstaller_path():
    """Inno Setup's uninstaller sits next to Mucify.exe (not present for the portable zip / dev runs)."""
    if not paths.FROZEN:
        return None
    folder = Path(sys.executable).resolve().parent
    for cand in sorted(folder.glob("unins*.exe")):
        return cand
    return None


def preview(cfg) -> dict:
    data = paths.user_data_dir()
    working = Path(cfg["paths"].get("working_dir") or paths.default_working_dir())
    music = Path(cfg["paths"].get("music_vault") or paths.default_music_dir())
    custom_working = not is_inside(working, data)
    pf = playlist_folders(working) if custom_working else []
    size, files = dir_stats(data)
    out = {
        "app_data": {"path": str(data), "size": size, "files": files},
        "playlists": {"custom_folder": custom_working, "path": str(working), "count": len(pf)},
        "music": {"path": str(music), "exists": music.exists(), "deletable": is_default_music(music)},
        "can_uninstall": uninstaller_path() is not None,
    }
    if out["music"]["exists"] and out["music"]["deletable"]:
        out["music"]["size"], out["music"]["files"] = dir_stats(music)
    return out


def launch_command() -> list:
    return [sys.executable] if paths.FROZEN else [sys.executable, "-m", "mucify"]


def build_plan(cfg, mode: str, delete_playlists: bool, delete_music: bool) -> dict:
    data = paths.user_data_dir()
    working = Path(cfg["paths"].get("working_dir") or paths.default_working_dir())
    music = Path(cfg["paths"].get("music_vault") or paths.default_music_dir())
    targets = [str(data)]
    if delete_playlists and not is_inside(working, data):
        targets += [str(d) for d in playlist_folders(working)]
    if delete_music and music.exists() and is_default_music(music):
        targets.append(str(music))
    unins = uninstaller_path() if mode == "uninstall" else None
    return {"mode": mode, "targets": targets, "pid": os.getpid(), "launch": launch_command(),
            "uninstaller": str(unins) if unins else ""}


# ----------------------------------------------------------------- doing it
def _wait_for_exit(pid, timeout=40.0):
    if not pid:
        return
    end = time.time() + timeout
    if os.name == "nt":
        try:
            import ctypes
            h = ctypes.windll.kernel32.OpenProcess(0x00100000, False, int(pid))   # SYNCHRONIZE
            if h:
                ctypes.windll.kernel32.WaitForSingleObject(h, int(timeout * 1000))
                ctypes.windll.kernel32.CloseHandle(h)
            return
        except Exception:
            pass
    while time.time() < end:
        try:
            os.kill(int(pid), 0)
        except OSError:
            return
        time.sleep(0.3)


def _make_writable(p: Path):
    for root, dirs, names in os.walk(p):
        for n in dirs + names:
            try:
                os.chmod(os.path.join(root, n), stat.S_IWRITE | stat.S_IREAD | stat.S_IEXEC)
            except OSError:
                pass


def delete_tree(p: Path, attempts: int = 20, pause: float = 1.0) -> bool:
    """rmtree with retries: right after the app exits, its browser engine may still hold files for a moment."""
    for i in range(attempts):
        if not p.exists():
            return True
        shutil.rmtree(p, ignore_errors=True)
        if not p.exists():
            return True
        _make_writable(p)
        time.sleep(pause)
    return not p.exists()


def apply_plan(plan: dict, wait: bool = True, pause: float = 1.0) -> list:
    """Returns a list of (path, reason) for anything that could not be removed."""
    if wait:
        _wait_for_exit(plan.get("pid"))
    targets = [Path(t) for t in plan.get("targets", [])]
    allowed = [t for t in targets if target_allowed(t)]          # decided up front, before anything is deleted
    failed = [(str(t), "not on the allow-list") for t in targets if t not in allowed]
    for t in allowed:
        if not delete_tree(t, pause=pause):
            failed.append((str(t), "could not be removed (in use?)"))
    return failed


def run_helper(plan_file: str) -> int:
    log = Path(tempfile.gettempdir()) / "mucify-wipe.log"
    try:
        plan = json.loads(Path(plan_file).read_text(encoding="utf-8"))
        failed = apply_plan(plan)
        log.write_text("failed: " + json.dumps(failed) if failed else "ok", encoding="utf-8")
        try:
            os.remove(plan_file)
        except OSError:
            pass
        kw = {"close_fds": True, "stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
        if os.name == "nt":
            kw["creationflags"] = DETACHED
        else:
            kw["start_new_session"] = True
        if plan.get("mode") == "uninstall" and plan.get("uninstaller") and os.path.exists(plan["uninstaller"]):
            subprocess.Popen([plan["uninstaller"]], **kw)
        elif plan.get("mode") == "reset":
            subprocess.Popen(plan["launch"], **kw)
        return 0
    except Exception as e:
        try:
            log.write_text(f"error: {e}", encoding="utf-8")
        except OSError:
            pass
        return 1


def spawn_helper(plan: dict) -> bool:
    f = tempfile.NamedTemporaryFile("w", prefix="mucify-wipe-", suffix=".json", delete=False, encoding="utf-8")
    json.dump(plan, f)
    f.close()
    cmd = launch_command() + ["--apply-wipe", f.name]
    kw = {"close_fds": True, "stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if os.name == "nt":
        kw["creationflags"] = DETACHED
    else:
        kw["start_new_session"] = True
    subprocess.Popen(cmd, **kw)
    return True
