# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 mageman007 and contributors
"""
Bridge between the Flask backend and the native desktop window.

main.py registers the pywebview window here; the backend then uses it for
native Open/Save/Folder dialogs and to open the Qobuz login window.
When running from source without a window (tests, development) it falls back
to tkinter dialogs so the backend still works.
"""
import os

main_window = None
_webview = None
_fullscreen = False
_pre_fullscreen = None      # window state from just before F11 fullscreen was entered

FILETYPES = {
    "csv": ["CSV files (*.csv)", "All files (*.*)"],
    "exe": ["Executable (*.exe)", "All files (*.*)"],
    "audio": ["Audio files (*.mp3;*.flac)", "All files (*.*)"],
    "any": ["All files (*.*)"],
}


def register(window, webview_module):
    global main_window, _webview
    main_window, _webview = window, webview_module


def webview_module():
    return _webview


def available() -> bool:
    return main_window is not None and _webview is not None


def _dialog_const(name):
    """pywebview >= 5 uses webview.FileDialog.X; older used webview.X_DIALOG."""
    fd = getattr(_webview, "FileDialog", None)
    if fd is not None and hasattr(fd, name):
        return getattr(fd, name)
    return getattr(_webview, f"{name}_DIALOG")


def _first(result):
    if not result:
        return None
    if isinstance(result, (list, tuple)):
        return result[0] if result else None
    return result


def pick(mode: str, filetype: str = "any", directory=None) -> dict:
    types = FILETYPES.get(filetype, FILETYPES["any"])
    directory = directory if directory and os.path.isdir(directory) else ""
    if available():
        if mode == "folder":
            res = main_window.create_file_dialog(_dialog_const("FOLDER"), directory=directory)
            return {"path": _first(res)}
        if mode == "files":
            res = main_window.create_file_dialog(_dialog_const("OPEN"), directory=directory,
                                                 allow_multiple=True, file_types=tuple(types))
            return {"paths": list(res or [])}
        res = main_window.create_file_dialog(_dialog_const("OPEN"), directory=directory,
                                             allow_multiple=False, file_types=tuple(types))
        return {"path": _first(res)}
    return _tk_pick(mode, filetype)


def save_dialog(filename: str):
    if available():
        res = main_window.create_file_dialog(_dialog_const("SAVE"), save_filename=filename,
                                             file_types=("CSV files (*.csv)", "All files (*.*)"))
        return _first(res)
    import tkinter as tk
    from tkinter import filedialog
    root = tk.Tk(); root.withdraw(); root.attributes("-topmost", True)
    try:
        return filedialog.asksaveasfilename(parent=root, initialfile=filename) or None
    finally:
        root.destroy()


def _tk_pick(mode, filetype):  # development fallback only
    import tkinter as tk
    from tkinter import filedialog
    tk_types = {"csv": [("CSV files", "*.csv"), ("All files", "*.*")],
                "exe": [("Executable", "*.exe"), ("All files", "*.*")],
                "audio": [("Audio files", "*.mp3 *.flac"), ("All files", "*.*")],
                "any": [("All files", "*.*")]}.get(filetype, [("All files", "*.*")])
    root = tk.Tk(); root.withdraw(); root.attributes("-topmost", True)
    try:
        if mode == "folder":
            return {"path": filedialog.askdirectory(parent=root) or None}
        if mode == "files":
            return {"paths": list(filedialog.askopenfilenames(parent=root, filetypes=tk_types))}
        return {"path": filedialog.askopenfilename(parent=root, filetypes=tk_types) or None}
    finally:
        root.destroy()


def quit_app():
    """Close every window, then make sure the process really ends."""
    import threading
    try:
        if _webview is not None:
            for w in list(_webview.windows):
                try:
                    w.destroy()
                except Exception:
                    pass
    finally:
        threading.Timer(2.0, lambda: os._exit(0)).start()


def toggle_fullscreen() -> bool:
    """F11. Returns True while the window is fullscreen. Fullscreen itself is never saved."""
    global _fullscreen, _pre_fullscreen
    if not available():
        return False
    from . import winstate
    if not _fullscreen:
        _pre_fullscreen = winstate.capture()           # remember maximized / position from before
    main_window.toggle_fullscreen()
    _fullscreen = not _fullscreen
    return _fullscreen


def state_to_save():
    """Window state to remember when closing: the normal/maximized state, never fullscreen."""
    from . import winstate
    if _fullscreen and _pre_fullscreen:
        return _pre_fullscreen
    return winstate.capture()
