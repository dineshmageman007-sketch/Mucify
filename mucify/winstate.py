# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 mageman007 and contributors
"""
Remember the main window: maximized or windowed, and where it sits and how big it is.

Windows only (plain Win32 calls through ctypes, so the numbers read and written are always in the
same units, whatever the display scaling). On other systems every function quietly does nothing.

  * saved to  %APPDATA%\\Mucify\\window.json  when the window closes
  * restored once the page has loaded (SetWindowPlacement: size, position and maximized in one step)
  * a saved position that is no longer on any screen (monitor unplugged) is ignored
  * F11 fullscreen is never saved: host.py keeps a snapshot from before fullscreen was entered
"""
import json
import os
import threading
import time

from . import paths

TITLE = "Mucify"
MIN_W, MIN_H = 960, 640            # same as the window's minimum size
MAX_W, MAX_H = 8000, 5000
_restored = False


# ----------------------------------------------------------------- pure helpers (testable anywhere)
def state_file():
    return paths.user_data_dir() / "window.json"


def save(state: dict) -> bool:
    try:
        tmp = state_file().with_suffix(".tmp")
        tmp.write_text(json.dumps(state), encoding="utf-8")
        os.replace(tmp, state_file())
        return True
    except OSError:
        return False


def load():
    try:
        data = json.loads(state_file().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def normalize(state, screens):
    """Return a safe state dict, or None if the saved one can't be used.
    screens = list of (left, top, right, bottom) rectangles of the connected monitors."""
    try:
        x, y, w, h = (int(state[k]) for k in ("x", "y", "w", "h"))
        maximized = bool(state.get("maximized", False))
    except (TypeError, KeyError, ValueError):
        return None
    if not (MIN_W <= w <= MAX_W and MIN_H <= h <= MAX_H):
        return None
    if screens:
        px, py = x + w // 2, y + 16                    # the middle of the title bar must be on some screen
        if not any(l <= px < r and t <= py < b for (l, t, r, b) in screens):
            return None
    return {"x": x, "y": y, "w": w, "h": h, "maximized": maximized}


# ----------------------------------------------------------------- Win32
if os.name == "nt":
    import ctypes
    from ctypes import wintypes

    _user32 = ctypes.windll.user32
    _SW_NORMAL, _SW_MINIMIZED, _SW_MAXIMIZED = 1, 2, 3
    _WPF_RESTORETOMAXIMIZED = 2

    class _WINDOWPLACEMENT(ctypes.Structure):
        _fields_ = [("length", wintypes.UINT), ("flags", wintypes.UINT), ("showCmd", wintypes.UINT),
                    ("ptMinPosition", wintypes.POINT), ("ptMaxPosition", wintypes.POINT),
                    ("rcNormalPosition", wintypes.RECT)]

    def _find_hwnd():
        found = []
        pid = os.getpid()
        proc_t = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def cb(hwnd, _lp):
            if not _user32.IsWindowVisible(hwnd):
                return True
            owner = wintypes.DWORD()
            _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
            if owner.value != pid:
                return True
            buf = ctypes.create_unicode_buffer(256)
            _user32.GetWindowTextW(hwnd, buf, 256)
            if buf.value == TITLE:
                found.append(hwnd)
                return False
            return True

        _user32.EnumWindows(proc_t(cb), 0)
        return found[0] if found else None

    def _screens():
        out = []
        proc_t = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC,
                                    ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)

        def cb(_hm, _hdc, lprc, _lp):
            r = lprc.contents
            out.append((r.left, r.top, r.right, r.bottom))
            return True

        _user32.EnumDisplayMonitors(None, None, proc_t(cb), 0)
        return out

    def capture():
        """Current window state, or None."""
        hwnd = _find_hwnd()
        if not hwnd:
            return None
        wp = _WINDOWPLACEMENT()
        wp.length = ctypes.sizeof(wp)
        if not _user32.GetWindowPlacement(hwnd, ctypes.byref(wp)):
            return None
        r = wp.rcNormalPosition                         # the *restored* rectangle, even while maximized
        maximized = wp.showCmd == _SW_MAXIMIZED or (wp.showCmd == _SW_MINIMIZED and bool(wp.flags & _WPF_RESTORETOMAXIMIZED))
        return {"x": r.left, "y": r.top, "w": r.right - r.left, "h": r.bottom - r.top, "maximized": maximized}

    def _apply(state) -> bool:
        hwnd = _find_hwnd()
        if not hwnd:
            return False
        wp = _WINDOWPLACEMENT()
        wp.length = ctypes.sizeof(wp)
        _user32.GetWindowPlacement(hwnd, ctypes.byref(wp))
        wp.rcNormalPosition = wintypes.RECT(state["x"], state["y"], state["x"] + state["w"], state["y"] + state["h"])
        wp.showCmd = _SW_MAXIMIZED if state["maximized"] else _SW_NORMAL
        return bool(_user32.SetWindowPlacement(hwnd, ctypes.byref(wp)))
else:
    def capture():
        return None

    def _screens():
        return []

    def _apply(state) -> bool:
        return False


# ----------------------------------------------------------------- called from main.py
def restore_async():
    """Once per run: put the window back the way the user left it (retries while the window appears)."""
    global _restored
    if _restored:
        return
    _restored = True
    state = normalize(load(), _screens())
    if not state:
        return

    def work():
        for _ in range(40):                              # up to ~8 s
            try:
                if _apply(state):
                    return
            except Exception:
                return
            time.sleep(0.2)

    threading.Thread(target=work, daemon=True).start()


def save_on_close(state=None):
    """Called when the window is closing. `state` lets host.py pass the pre-fullscreen snapshot."""
    try:
        state = state or capture()
        if state and normalize(state, []):
            save(state)
    except Exception:
        pass
