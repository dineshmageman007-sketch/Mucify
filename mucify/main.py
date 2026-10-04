# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 mageman007 and contributors
"""
Mucify desktop launcher.

Starts the Flask backend on a random private port (127.0.0.1) in a background
thread and shows it in a native window (Microsoft Edge WebView2 via pywebview).
No browser, no console, no manual server - just a normal Windows app.
"""
import os
import socket
import sys
import threading
import time
import traceback


def _quiet_stdio():
    """Windowed PyInstaller apps have no console: sys.stdout/stderr are None."""
    log = None
    try:
        from . import paths
        log = open(paths.logs_dir() / "mucify.log", "a", encoding="utf-8", buffering=1)
    except Exception:
        pass
    for name in ("stdout", "stderr"):
        if getattr(sys, name) is None:
            setattr(sys, name, log or open(os.devnull, "w"))


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _serve(flask_app, port):
    from werkzeug.serving import make_server
    server = make_server("127.0.0.1", port, flask_app, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def _wait_ready(port, timeout=15.0):
    end = time.time() + timeout
    while time.time() < end:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.1)
    return False


def _error_box(title, text):
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, text, title, 0x10)
            return
        except Exception:
            pass
    print(f"{title}: {text}", file=sys.stderr)


def selftest() -> int:
    """`Mucify.exe --selftest`: headless check used by the build pipeline.
    Verifies the packaged app can serve its UI and find its bundled tools,
    writes a report to <data dir>/logs/selftest.txt and returns an exit code."""
    lines, failed = [], False

    def check(name, ok, fatal=True):
        nonlocal failed
        lines.append(f"[{'OK' if ok else ('FAIL' if fatal else 'WARN')}] {name}")
        if not ok and fatal:
            failed = True

    try:
        from . import __version__, paths
        from .app import app as flask_app, load_config, resolve_tool_path
        lines.append(f"Mucify {__version__}  frozen={paths.FROZEN}  bundle={paths.bundle_root()}")
        c = flask_app.test_client()
        check("UI page served", c.get("/").status_code == 200)
        check("stylesheet served", c.get("/static/style.css").status_code == 200)
        check("script served", c.get("/static/app.js").status_code == 200)
        check("setup endpoint answers", c.get("/api/setup/state").status_code == 200)
        cfg = load_config()
        sldl = resolve_tool_path(cfg, "sldl_exe", "sldl.exe")
        rsg = resolve_tool_path(cfg, "rsgain_exe", "rsgain.exe")
        check(f"sldl.exe found ({sldl})", bool(sldl and os.path.exists(sldl)))
        check(f"rsgain.exe found ({rsg})", bool(rsg and os.path.exists(rsg)))
        check("icon bundled", (paths.bundle_root() / "assets" / "mucify.ico").exists())
        for doc in ("license", "third_party", "disclaimer", "privacy", "credits", "sldl_license", "rsgain_license"):
            f = paths.legal_file(doc)
            check(f"legal document bundled: {doc}", bool(f and f.exists()))
        try:
            import mutagen.flac  # noqa: F401
            check("mutagen importable", True)
        except Exception as e:
            check(f"mutagen importable ({e})", False)
        try:
            import webview  # noqa: F401
            check("pywebview importable", True, fatal=False)
        except Exception as e:
            check(f"pywebview importable ({e})", False, fatal=False)
        if os.name == "nt":
            try:
                import clr  # noqa: F401
                check("pythonnet (clr) importable", True, fatal=False)
            except Exception as e:
                check(f"pythonnet (clr) importable ({e})", False, fatal=False)
    except Exception:
        lines.append(traceback.format_exc())
        failed = True
    report = "\n".join(lines) + ("\nRESULT: FAILED" if failed else "\nRESULT: PASSED") + "\n"
    try:
        from . import paths
        (paths.logs_dir() / "selftest.txt").write_text(report, encoding="utf-8")
    except Exception:
        pass
    print(report)
    return 1 if failed else 0


def main():
    if "--apply-wipe" in sys.argv:                      # helper started by Reset / Uninstall (no window)
        from . import reset
        i = sys.argv.index("--apply-wipe")
        raise SystemExit(reset.run_helper(sys.argv[i + 1]) if len(sys.argv) > i + 1 else 1)
    if "--selftest" in sys.argv:
        _quiet_stdio()
        raise SystemExit(selftest())
    _quiet_stdio()
    # one running instance only (Windows named mutex)
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.kernel32.CreateMutexW(None, False, "Mucify.SingleInstance")
            if ctypes.windll.kernel32.GetLastError() == 183:  # ALREADY_EXISTS
                _error_box("Mucify", "Mucify is already running.")
                return
        except Exception:
            pass
    try:
        import webview
        from . import __version__, paths, host
        from .app import app as flask_app

        port = _free_port()
        _serve(flask_app, port)
        if not _wait_ready(port):
            raise RuntimeError("The internal Mucify service didn't start.")

        # let the optional background music start without a click (Chromium's autoplay rule)
        os.environ.setdefault("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS", "--autoplay-policy=no-user-gesture-required")
        icon = paths.bundle_root() / "assets" / "mucify.ico"
        window = webview.create_window(
            "Mucify", f"http://127.0.0.1:{port}/", width=1240, height=860, min_size=(960, 640),
            background_color="#0e0e12", text_select=True)
        host.register(window, webview)
        from . import winstate
        window.events.loaded += lambda *a: winstate.restore_async()
        window.events.closing += lambda *a: winstate.save_on_close(host.state_to_save())
        webview.start(private_mode=False, storage_path=str(paths.webview_storage_dir()),
                      icon=str(icon) if icon.exists() else None)
    except Exception:
        err = traceback.format_exc()
        try:
            from . import paths
            (paths.logs_dir() / "crash.log").write_text(err, encoding="utf-8")
        except Exception:
            pass
        _error_box("Mucify couldn't start",
                   "Mucify needs the Microsoft Edge WebView2 Runtime (included with Windows 10/11 and "
                   "installed by the Mucify setup).\n\nDetails were saved to %APPDATA%\\Mucify\\logs\\crash.log")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
