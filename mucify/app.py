# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 mageman007 and contributors
"""
Mucify - backend (Flask, served privately to the desktop window)
-----------------------------------------------------------------
Four domains behind one UI:

  1. Playlist Manager  - dedupe a "to download" CSV against a library of
                          already-downloaded tracks (Spotify Track Id based)
  2. Qobuz Enrich       - clean a raw chosic.com playlist export and attach
                          official max bit-depth / sample-rate from Qobuz
  3. Downloader         - run the enriched CSV through the bundled, tested
                          sldl.exe (Soulseek) with quality-ceiling/floor
                          filtering and slow-peer abandonment
  4. Post-Processing    - run the bundled rsgain.exe over a FLAC library
                          folder to write ReplayGain 2.0 tags

User data (config, library index, CSVs) lives in %APPDATA%\\Mucify.
Nothing is downloaded at runtime: sldl.exe and rsgain.exe ship with the app.
This module is started by mucify/main.py (desktop window) - not by hand.
"""

import csv
import io
import json
import os
import re
import subprocess
import threading
import queue
import time
from collections import defaultdict
from pathlib import Path
from datetime import datetime

from flask import Flask, request, jsonify, send_file, send_from_directory, Response

from . import audiometa, __version__, __author__, __license__, __copyright__, __url__, paths, soulseek, host, qobuz_auth, projects, reset

DATA_DIR = paths.data_dir()
CONFIG_PATH = paths.config_path()
LIBRARY_PATH = DATA_DIR / "library.json"
SOURCES_PATH = DATA_DIR / "sources.json"
RECENT_PATH = DATA_DIR / "recent.json"
UPLOADS_DIR = paths.uploads_dir()

app = Flask(__name__, static_folder=None)
app.config["MAX_CONTENT_LENGTH"] = 200 * 1024 * 1024

# Windowed (no console) app: child processes must not flash a console window
# and must never wait on stdin.
SUBPROC_KW = {"stdin": subprocess.DEVNULL}
if os.name == "nt":
    SUBPROC_KW["creationflags"] = 0x08000000  # CREATE_NO_WINDOW

_ALLOWED_HOSTS = {"127.0.0.1", "localhost"}


@app.before_request
def _guard():
    """The backend only listens on 127.0.0.1, but a web page in the user's
    normal browser could still try to reach it. Reject foreign Host headers
    (DNS rebinding) and require a custom header on every write request, which
    browsers will not send cross-site without a CORS preflight we never grant."""
    hostname = (request.host or "").rsplit(":", 1)[0].strip("[]")
    if hostname not in _ALLOWED_HOSTS:
        return jsonify({"error": "forbidden"}), 403
    if request.method not in ("GET", "HEAD") and request.headers.get("X-Mucify") != "1":
        return jsonify({"error": "forbidden"}), 403


# Qobuz's web player itself uses this App ID for every visitor - it's not
# personal, so if the (advanced) App ID field is blank fall back to this.
QOBUZ_DEFAULT_APP_ID = qobuz_auth.DEFAULT_APP_ID

DEFAULT_CONFIG = {
    "app": {"first_run_done": False, "bgm_enabled": False, "bgm_path": "", "bgm_volume": 0.4},
    "qobuz": {"app_id": "", "user_id": "", "token": "",
              "status": ""},          # "" | "ok" | "expired"
    "soulseek": {"username": "", "password": "", "verified": False},
    "paths": {
        # Manual overrides only (Settings > Advanced). By default the bundled,
        # tested copies shipped inside Mucify are used.
        "sldl_exe": "",
        "rsgain_exe": "",
        "music_vault": "",
        "working_dir": "",
    },
}


def resolve_tool_path(cfg, key, filename):
    """Manual override wins if set and still exists; otherwise the bundled,
    tested copy that ships with Mucify (never downloaded)."""
    return paths.resolve_tool(cfg["paths"].get(key, ""), filename)


# ============================================================
# CONFIG (credentials + paths) - %APPDATA%\\Mucify\\config.json
# ============================================================
def _fresh_default():
    return json.loads(json.dumps(DEFAULT_CONFIG))


def load_config():
    if not CONFIG_PATH.exists():
        cfg = _fresh_default()
    else:
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except (json.JSONDecodeError, OSError):
            cfg = _fresh_default()
    changed = not CONFIG_PATH.exists()
    for section, defaults in DEFAULT_CONFIG.items():
        if not isinstance(cfg.get(section), dict):
            cfg[section] = {}
            changed = True
        for k, v in defaults.items():
            if k not in cfg[section]:
                cfg[section][k] = v
                changed = True
    # Folders default to Music\\Mucify and %APPDATA%\\Mucify\\Working
    if not cfg["paths"]["music_vault"]:
        cfg["paths"]["music_vault"] = str(paths.default_music_dir()); changed = True
    if not cfg["paths"]["working_dir"]:
        cfg["paths"]["working_dir"] = str(paths.default_working_dir()); changed = True
    if changed:
        save_config(cfg)
    return cfg


def save_config(cfg):
    tmp = CONFIG_PATH.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    os.replace(tmp, CONFIG_PATH)


def _ensure_dir(path_str):
    try:
        Path(path_str).mkdir(parents=True, exist_ok=True)
        return True
    except Exception:
        return False


def _settings_payload(cfg):
    detected = {
        "sldl_exe": resolve_tool_path(cfg, "sldl_exe", "sldl.exe"),
        "rsgain_exe": resolve_tool_path(cfg, "rsgain_exe", "rsgain.exe"),
    }
    return {**cfg, "detected": detected,
            "defaults": {"music_vault": str(paths.default_music_dir()),
                         "working_dir": str(paths.default_working_dir())}}


@app.route("/api/settings", methods=["GET"])
def get_settings():
    return jsonify(_settings_payload(load_config()))


@app.route("/api/settings", methods=["POST"])
def set_settings():
    incoming = request.json or {}
    cfg = load_config()
    old_token = cfg["qobuz"].get("token", "")
    old_user = cfg["soulseek"].get("username", ""), cfg["soulseek"].get("password", "")
    for section in ("qobuz", "soulseek", "paths", "app"):
        if isinstance(incoming.get(section), dict):
            cfg[section].update(incoming[section])
    if cfg["qobuz"].get("token", "") != old_token:
        cfg["qobuz"]["status"] = "ok" if cfg["qobuz"]["token"].strip() else ""
    if (cfg["soulseek"].get("username", ""), cfg["soulseek"].get("password", "")) != old_user:
        cfg["soulseek"]["verified"] = False
    for k in ("music_vault", "working_dir"):
        if cfg["paths"].get(k):
            _ensure_dir(cfg["paths"][k])
    save_config(cfg)
    return jsonify({"ok": True, "config": _settings_payload(cfg)})


# ============================================================
# FIRST-RUN SETUP + SOULSEEK + QOBUZ CONNECT
# ============================================================
@app.route("/api/setup/state")
def setup_state():
    cfg = load_config()
    return jsonify({
        "first_run_done": bool(cfg["app"].get("first_run_done")),
        "defaults": {"music_vault": str(paths.default_music_dir()),
                     "working_dir": str(paths.default_working_dir())},
        "suggested": {"username": soulseek.random_username(),
                      "password": soulseek.random_password()},
        "tools": {"sldl": bool(resolve_tool_path(cfg, "sldl_exe", "sldl.exe")),
                  "rsgain": bool(resolve_tool_path(cfg, "rsgain_exe", "rsgain.exe"))},
        "qobuz_connected": bool(cfg["qobuz"].get("token")) and cfg["qobuz"].get("status") != "expired",
        "webview": host.available(),
        "version": __version__,
    })


@app.route("/api/setup/complete", methods=["POST"])
def setup_complete():
    """Create the default folders and mark first-run as finished.
    body (all optional): {username, password}"""
    body = request.json or {}
    cfg = load_config()
    if body.get("username") is not None:
        cfg["soulseek"]["username"] = str(body["username"]).strip()
    if body.get("password") is not None:
        cfg["soulseek"]["password"] = str(body["password"])
    for k in ("music_vault", "working_dir"):
        if not _ensure_dir(cfg["paths"][k]):
            return jsonify({"error": f"Couldn't create folder: {cfg['paths'][k]}"}), 500
    cfg["app"]["first_run_done"] = True
    save_config(cfg)
    return jsonify({"ok": True})


@app.route("/api/random-credential")
def random_credential():
    kind = request.args.get("kind", "username")
    return jsonify({"value": soulseek.random_password() if kind == "password" else soulseek.random_username()})


@app.route("/api/soulseek/test", methods=["POST"])
def soulseek_test():
    body = request.json or {}
    cfg = load_config()
    user = body.get("username", cfg["soulseek"]["username"])
    pw = body.get("password", cfg["soulseek"]["password"])
    result = soulseek.test_login(user, pw)
    # remember the verdict only if it was for the saved credentials
    if user == cfg["soulseek"]["username"] and pw == cfg["soulseek"]["password"]:
        cfg["soulseek"]["verified"] = bool(result["ok"])
        save_config(cfg)
    return jsonify(result)


@app.route("/api/qobuz/connect", methods=["POST"])
def qobuz_connect():
    """Open the in-app Qobuz login window; the token is captured automatically."""
    status = qobuz_auth.start_connect(on_token=_on_qobuz_token)
    return jsonify(status)


@app.route("/api/qobuz/connect/status")
def qobuz_connect_status():
    return jsonify(qobuz_auth.connect_status())


@app.route("/api/qobuz/connect/cancel", methods=["POST"])
def qobuz_connect_cancel():
    qobuz_auth.cancel_connect()
    return jsonify({"ok": True})


@app.route("/api/qobuz/token", methods=["POST"])
def qobuz_manual_token():
    """Manual fallback: validate + save a pasted token."""
    token = ((request.json or {}).get("token") or "").strip().strip('"')
    if not token:
        return jsonify({"ok": False, "message": "Paste the token first."}), 400
    cfg = load_config()
    app_id = cfg["qobuz"].get("app_id", "").strip() or QOBUZ_DEFAULT_APP_ID
    verdict = qobuz_auth.validate_token(token, app_id)
    if verdict == "invalid":
        return jsonify({"ok": False, "message": "Qobuz rejected that token. Make sure you copied the whole value "
                                                "of X-User-Auth-Token."}), 400
    _on_qobuz_token(token, app_id=None)
    msg = "Qobuz connected." if verdict == "ok" else \
        "Token saved, but Qobuz couldn't be reached to confirm it (network/VPN?). It will be checked on first use."
    return jsonify({"ok": True, "message": msg})


@app.route("/api/qobuz/disconnect", methods=["POST"])
def qobuz_disconnect():
    cfg = load_config()
    cfg["qobuz"].update(token="", user_id="", status="")
    save_config(cfg)
    return jsonify({"ok": True})


@app.route("/api/qobuz/validate", methods=["POST"])
def qobuz_validate():
    cfg = load_config()
    token = cfg["qobuz"].get("token", "").strip()
    if not token:
        return jsonify({"state": "none"})
    app_id = cfg["qobuz"].get("app_id", "").strip() or QOBUZ_DEFAULT_APP_ID
    verdict = qobuz_auth.validate_token(token, app_id)
    if verdict == "invalid":
        _mark_qobuz_expired()
        return jsonify({"state": "expired"})
    if verdict == "ok":
        cfg["qobuz"]["status"] = "ok"
        save_config(cfg)
    return jsonify({"state": verdict})


def _on_qobuz_token(token, app_id=None, user_id=None):
    cfg = load_config()
    cfg["qobuz"]["token"] = token
    cfg["qobuz"]["status"] = "ok"
    if user_id:
        cfg["qobuz"]["user_id"] = str(user_id)
    save_config(cfg)


def _mark_qobuz_expired():
    cfg = load_config()
    if cfg["qobuz"].get("token"):
        cfg["qobuz"]["status"] = "expired"
        save_config(cfg)


def _working_dir():
    wd = Path(load_config()["paths"]["working_dir"] or paths.default_working_dir())
    wd.mkdir(parents=True, exist_ok=True)
    return wd


@app.route("/api/recent")
def recent_files():
    """What the floating 'last file' card offers on each screen."""
    cfg = load_config()
    return jsonify({**projects.recent(RECENT_PATH), "library_folder": cfg["paths"].get("music_vault", "")})


@app.route("/api/window/fullscreen", methods=["POST"])
def window_fullscreen():
    """F11: toggle fullscreen on the app window (not remembered between runs)."""
    if not host.available():
        return jsonify({"ok": False, "fullscreen": False})
    return jsonify({"ok": True, "fullscreen": host.toggle_fullscreen()})


# ============================================================
# ABOUT & LEGAL (license, credits, disclaimers - shown in Settings)
# ============================================================
@app.route("/api/about")
def about_info():
    return jsonify({
        "name": "Mucify", "version": __version__, "author": __author__, "license": __license__,
        "copyright": __copyright__, "url": __url__,
        "docs": [{"id": i, "title": paths.legal_title(i)} for i in list(paths.LEGAL_DOCS) + list(paths.TOOL_LICENSES)],
    })


@app.route("/api/legal/<doc_id>")
def legal_doc(doc_id):
    path = paths.legal_file(doc_id)            # only ids from a fixed allow-list resolve to a file
    if path is None or not path.is_file():
        return jsonify({"error": "Document not found"}), 404
    return jsonify({"id": doc_id, "title": paths.legal_title(doc_id),
                    "text": path.read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n")})


# ============================================================
# BACKGROUND MUSIC (optional, user's own MP3 / FLAC file, looped in the UI)
# ============================================================
BGM_TYPES = {".mp3": "audio/mpeg", ".flac": "audio/flac"}
BGM_MAX_TRACKS = 5000


def bgm_list_tracks(folder):
    """MP3/FLAC files in a folder (and its sub-folders), in a stable order."""
    out = []
    for root, dirs, names in os.walk(folder):
        dirs.sort()
        for n in sorted(names, key=str.lower):
            if os.path.splitext(n)[1].lower() in BGM_TYPES:
                out.append(os.path.join(root, n))
                if len(out) >= BGM_MAX_TRACKS:
                    return out
    return out


@app.route("/api/bgmusic")
def bgmusic_file():
    """Single-file mode: the chosen file."""
    p = load_config()["app"].get("bgm_path", "")
    ext = os.path.splitext(p)[1].lower()
    if not p or ext not in BGM_TYPES or not os.path.isfile(p):
        return jsonify({"error": "No background music file"}), 404
    return send_file(p, mimetype=BGM_TYPES[ext], conditional=True, max_age=0)


@app.route("/api/bgmusic/tracks")
def bgmusic_tracks():
    p = load_config()["app"].get("bgm_path", "")
    if p and os.path.isdir(p):
        tracks = bgm_list_tracks(p)
        return jsonify({"kind": "folder", "tracks": [{"i": i, "name": os.path.splitext(os.path.basename(t))[0]}
                                                     for i, t in enumerate(tracks)]})
    if p and os.path.isfile(p):
        return jsonify({"kind": "file", "tracks": [{"i": 0, "name": os.path.splitext(os.path.basename(p))[0]}]})
    return jsonify({"kind": "none", "tracks": []})


@app.route("/api/bgmusic/track/<int:i>")
def bgmusic_track(i):
    """Folder mode: one track of the chosen folder, by its position in /api/bgmusic/tracks."""
    p = load_config()["app"].get("bgm_path", "")
    if not p or not os.path.isdir(p):
        return jsonify({"error": "No background music folder"}), 404
    tracks = bgm_list_tracks(p)
    if i < 0 or i >= len(tracks) or not os.path.isfile(tracks[i]):
        return jsonify({"error": "Track not found"}), 404
    return send_file(tracks[i], mimetype=BGM_TYPES[os.path.splitext(tracks[i])[1].lower()],
                     conditional=True, max_age=0)


def _bgm_current_file(i=None):
    """Path of the track the mini player is showing (folder mode: its index; file mode: the file)."""
    p = load_config()["app"].get("bgm_path", "")
    if p and os.path.isdir(p):
        tracks = bgm_list_tracks(p)
        return tracks[i] if i is not None and 0 <= i < len(tracks) else None
    if p and os.path.isfile(p) and i is None and os.path.splitext(p)[1].lower() in BGM_TYPES:
        return p
    return None


@app.route("/api/bgmusic/meta")
@app.route("/api/bgmusic/meta/<int:i>")
def bgmusic_meta(i=None):
    f = _bgm_current_file(i)
    if not f or not os.path.isfile(f):
        return jsonify({"error": "No such track"}), 404
    return jsonify(audiometa.read_info(f))


@app.route("/api/bgmusic/art")
@app.route("/api/bgmusic/art/<int:i>")
def bgmusic_art(i=None):
    f = _bgm_current_file(i)
    cover = audiometa.read_cover(f) if f and os.path.isfile(f) else None
    if not cover:
        return jsonify({"error": "No cover art"}), 404
    return Response(cover[1], mimetype=cover[0], headers={"Cache-Control": "max-age=3600"})


@app.route("/api/bgmusic/set", methods=["POST"])
def bgmusic_set():
    """Accepts one MP3/FLAC file (looped) or a folder of them (shuffled)."""
    p = ((request.json or {}).get("path") or "").strip().strip('"')
    if os.path.isdir(p):
        count = len(bgm_list_tracks(p))
        if not count:
            return jsonify({"error": "No MP3 or FLAC files were found in that folder."}), 400
        kind = "folder"
    else:
        if os.path.splitext(p)[1].lower() not in BGM_TYPES:
            return jsonify({"error": "Please choose an MP3 or FLAC file, or a folder that contains them."}), 400
        if not os.path.isfile(p):
            return jsonify({"error": "That file wasn't found."}), 404
        kind, count = "file", 1
    cfg = load_config()
    cfg["app"].update(bgm_path=p, bgm_enabled=True)
    save_config(cfg)
    return jsonify({"ok": True, "kind": kind, "count": count, "name": os.path.basename(p.rstrip("\\/")) or p})


@app.route("/api/bgmusic/clear", methods=["POST"])
def bgmusic_clear():
    cfg = load_config()
    cfg["app"].update(bgm_path="", bgm_enabled=False)
    save_config(cfg)
    return jsonify({"ok": True})


# ============================================================
# RESET / UNINSTALL (wipes every folder Mucify created; see reset.py)
# ============================================================
@app.route("/api/reset/preview")
def reset_preview():
    return jsonify(reset.preview(load_config()))


@app.route("/api/reset/run", methods=["POST"])
def reset_run():
    body = request.json or {}
    mode = "uninstall" if body.get("mode") == "uninstall" else "reset"
    if qobuz_job.running or downloader_job.running or postprocess_job.running:
        return jsonify({"error": "A job is still running. Stop it first, then try again."}), 409
    plan = reset.build_plan(load_config(), mode, bool(body.get("delete_playlists")), bool(body.get("delete_music")))
    try:
        reset.spawn_helper(plan)
    except Exception as e:
        return jsonify({"error": f"Couldn't start the clean-up ({e})."}), 500
    threading.Timer(0.8, host.quit_app).start()
    return jsonify({"ok": True, "mode": mode, "uninstaller": bool(plan["uninstaller"])})


# ============================================================
# NATIVE FILE / FOLDER PICKER - used by every "Browse" button
# ============================================================
@app.route("/api/browse", methods=["POST"])
def browse():
    """body: { "mode": "file" | "files" | "folder", "filetypes": "csv"|"exe"|"any" }
    Opens the native Windows dialog from the Mucify window."""
    body = request.json or {}
    mode = body.get("mode", "file")
    filetype = body.get("filetypes", "any")
    try:
        return jsonify(host.pick(mode, filetype, body.get("directory")))
    except Exception as e:
        return jsonify({"error": f"Couldn't open the file dialog ({e}). Type the path instead."}), 500


@app.route("/api/export", methods=["POST"])
def export_file():
    """'Save as...' for generated CSVs (browser-style <a download> links don't
    work inside the desktop window). body: {path}"""
    body = request.json or {}
    src = body.get("path")
    if body.get("filename"):                      # generated files kept in the data folder
        src = str(DATA_DIR / os.path.basename(body["filename"]))
    if not src or not os.path.isfile(src):
        return jsonify({"error": "File not found"}), 404
    dest = host.save_dialog(os.path.basename(src))
    if not dest:
        return jsonify({"ok": False, "cancelled": True})
    import shutil
    shutil.copyfile(src, dest)
    return jsonify({"ok": True, "path": dest})


@app.route("/api/open-url", methods=["POST"])
def open_url():
    """External links (chosic.com, play.qobuz.com ...) open in the user's browser."""
    url = ((request.json or {}).get("url") or "").strip()
    if not url.lower().startswith("https://"):
        return jsonify({"error": "Only https links can be opened"}), 400
    import webbrowser
    webbrowser.open(url)
    return jsonify({"ok": True})


@app.route("/api/open-folder", methods=["POST"])
def open_folder():
    target = (request.json or {}).get("path")
    if not target or not os.path.exists(target):
        return jsonify({"error": "Folder not found"}), 404
    try:
        if os.name == "nt":
            if os.path.isfile(target):
                subprocess.Popen(["explorer", "/select,", os.path.normpath(target)], **SUBPROC_KW)
            else:
                os.startfile(os.path.normpath(target))  # noqa
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/upload", methods=["POST"])
def upload_file():
    """Generic upload used by drag-and-drop areas: saves the file into
    data/uploads and returns the resulting local path, so every domain's
    backend logic only ever deals in real filesystem paths."""
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400
    f = request.files["file"]
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_name = f"{ts}_{os.path.basename(f.filename)}"
    dest = UPLOADS_DIR / safe_name
    f.save(dest)
    return jsonify({"path": str(dest)})


# ============================================================
# SSE EVENT BUS (shared pattern for Qobuz Enrich, Downloader,
# and Post-Processing — each gets its own queue + run flag)
# ============================================================
class Job:
    def __init__(self):
        self.queue = queue.Queue()
        self.running = False
        self.stop_flag = threading.Event()

    def emit(self, type_, **kwargs):
        self.queue.put({"type": type_, **kwargs})

    def stream(self):
        def gen():
            while True:
                try:
                    msg = self.queue.get(timeout=30)
                    yield f"data: {json.dumps(msg)}\n\n"
                except queue.Empty:
                    yield f"data: {json.dumps({'type': 'ping'})}\n\n"
        return Response(gen(), mimetype="text/event-stream",
                         headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


qobuz_job = Job()
downloader_job = Job()
postprocess_job = Job()


# ============================================================
# DOMAIN 1 — PLAYLIST MANAGER  (dedupe against library.json)
# ============================================================
def load_library():
    if not LIBRARY_PATH.exists():
        return {}
    with open(LIBRARY_PATH, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {}


def save_library(library):
    with open(LIBRARY_PATH, "w", encoding="utf-8") as f:
        json.dump(library, f, ensure_ascii=False, indent=2)


def load_sources():
    if not SOURCES_PATH.exists():
        return []
    with open(SOURCES_PATH, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return []


def save_sources(sources):
    with open(SOURCES_PATH, "w", encoding="utf-8") as f:
        json.dump(sources, f, ensure_ascii=False, indent=2)


def read_csv_rows_from_path(path):
    with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
        reader = csv.DictReader(f)
        rows = [row for row in reader]
        return rows, reader.fieldnames


def get_track_id(row):
    for key in row.keys():
        if key.strip().lower() in ("spotify track id", "track id", "spotify_track_id"):
            val = row.get(key)
            if val:
                return val.strip()
    return None


def get_field(row, candidates):
    for key in row.keys():
        if key.strip().lower() in candidates:
            val = row.get(key)
            if val is not None and str(val).strip():
                return str(val).strip()
    return None


TITLE_CANDIDATES = {"track name", "song", "song title", "title", "name"}
ARTIST_CANDIDATES = {"artist name(s)", "artist name", "artist", "artists"}
DURATION_MS_CANDIDATES = {"track duration (ms)", "duration (ms)", "duration_ms", "length (ms)"}
DURATION_DIRECT_CANDIDATES = {"duration", "length", "track length"}


def get_title(row):
    return get_field(row, TITLE_CANDIDATES) or "Unknown"


def get_artist(row):
    return get_field(row, ARTIST_CANDIDATES) or "Unknown"


def get_length(row):
    ms_val = get_field(row, DURATION_MS_CANDIDATES)
    if ms_val:
        try:
            total_seconds = int(float(ms_val)) // 1000
            return f"{total_seconds // 60}:{total_seconds % 60:02d}"
        except (ValueError, TypeError):
            pass
    return get_field(row, DURATION_DIRECT_CANDIDATES) or ""


@app.route("/api/playlist/status")
def playlist_status():
    return jsonify({"count": len(load_library())})


@app.route("/api/playlist/upload", methods=["POST"])
def playlist_upload():
    """Ingest one or more 'already downloaded' CSVs (by local path) into the library."""
    paths = (request.json or {}).get("paths", [])
    if not paths:
        return jsonify({"error": "No files given"}), 400

    library = load_library()
    sources = load_sources()
    added = duplicates = skipped_no_id = total_rows = 0

    for p in paths:
        rows, _ = read_csv_rows_from_path(p)
        file_added = file_dup = file_skip = 0
        for row in rows:
            total_rows += 1
            track_id = get_track_id(row)
            if not track_id:
                skipped_no_id += 1
                file_skip += 1
                continue
            if track_id in library:
                duplicates += 1
                file_dup += 1
                continue
            row_with_source = dict(row)
            row_with_source["_source_file"] = os.path.basename(p)
            library[track_id] = row_with_source
            added += 1
            file_added += 1
        sources.append({
            "filename": os.path.basename(p), "rows": len(rows), "added": file_added,
            "duplicates": file_dup, "skipped_no_id": file_skip,
            "fed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })

    save_library(library)
    save_sources(sources)
    return jsonify({"added": added, "duplicates": duplicates, "skipped_no_id": skipped_no_id,
                     "total_rows_seen": total_rows, "library_size": len(library)})


@app.route("/api/playlist/clear", methods=["POST"])
def playlist_clear():
    save_library({})
    save_sources([])
    return jsonify({"library_size": 0})


def write_library_csv(library, dest):
    """Whole library -> one CSV (all columns of every track; re-importable via 'Add to library')."""
    fields = []
    for row in library.values():
        for k in row.keys():
            if k and k not in fields:
                fields.append(k)
    with open(dest, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for row in library.values():
            w.writerow({k: row.get(k, "") for k in fields})
    return len(library)


@app.route("/api/playlist/backup", methods=["POST"])
def playlist_backup():
    library = load_library()
    if not library:
        return jsonify({"error": "Your library is empty - there is nothing to back up yet."}), 400
    dest = host.save_dialog(f"Mucify library backup {datetime.now():%Y-%m-%d}.csv")
    if not dest:
        return jsonify({"ok": False, "cancelled": True})
    try:
        count = write_library_csv(library, dest)
    except OSError as e:
        return jsonify({"error": f"Couldn't save the backup: {e}"}), 500
    return jsonify({"ok": True, "path": dest, "count": count})


@app.route("/api/playlist/sources")
def playlist_sources():
    sources = list(reversed(load_sources()))
    return jsonify({"count": len(sources), "sources": sources})


@app.route("/api/playlist/compare", methods=["POST"])
def playlist_compare():
    """body: {"path": "<local path to the 'to download' csv>"}"""
    path = (request.json or {}).get("path")
    if not path or not os.path.exists(path):
        return jsonify({"error": "File not found"}), 400

    library = load_library()
    rows, fieldnames = read_csv_rows_from_path(path)

    already_have, to_download, table_rows = [], [], []
    for idx, row in enumerate(rows, start=1):
        track_id = get_track_id(row)
        is_have = bool(track_id and track_id in library)
        (already_have if is_have else to_download).append(row)
        table_rows.append({
            "position": idx, "title": get_title(row), "artist": get_artist(row),
            "length": get_length(row),
            "condition": "Already Added" if is_have else "To Download",
            "location": (library[track_id].get("_source_file") if is_have else os.path.basename(path)) or "Unknown",
        })

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    already_have_path = DATA_DIR / f"already_have_{ts}.csv"
    to_download_path = DATA_DIR / f"to_download_{ts}.csv"

    def write_csv(out_path, data_rows):
        with open(out_path, "w", newline="", encoding="utf-8") as f:
            if fieldnames:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(data_rows)

    write_csv(already_have_path, already_have)
    write_csv(to_download_path, to_download)

    # Automatically keep the to-download list in this playlist's own folder.
    playlist_folder = saved_path = None
    name = projects.playlist_name_from_path(path)
    try:
        projects.remember(RECENT_PATH, "source", path, name, len(rows))
        if to_download:
            playlist_folder = projects.folder_for_input(_working_dir(), path)
            playlist_folder.mkdir(parents=True, exist_ok=True)
            saved_path = projects.stage_path(playlist_folder, "to_download")
            import shutil
            shutil.copyfile(to_download_path, saved_path)
            projects.remember(RECENT_PATH, "to_download", saved_path, playlist_folder.name, len(to_download))
    except OSError as e:
        saved_path = None
        playlist_folder = None
        print(f"Could not save into the playlist folder: {e}")

    return jsonify({
        "already_have_count": len(already_have), "to_download_count": len(to_download),
        "total_rows": len(rows), "already_have_file": already_have_path.name,
        "to_download_file": to_download_path.name, "table_rows": table_rows,
        "playlist_name": name,
        "playlist_folder": str(playlist_folder) if playlist_folder else None,
        "saved_file": str(saved_path) if saved_path else None,
    })


@app.route("/api/playlist/download/<filename>")
def playlist_download(filename):
    safe_name = os.path.basename(filename)
    if not (safe_name.startswith("already_have_") or safe_name.startswith("to_download_")):
        return jsonify({"error": "Invalid file"}), 400
    path = DATA_DIR / safe_name
    if not path.exists():
        return jsonify({"error": "File not found"}), 404
    return send_file(path, as_attachment=True, download_name=safe_name)


# ============================================================
# DOMAIN 2 — QOBUZ ENRICH
# ============================================================
def clean_and_extract(text):
    if not text:
        return text, ""
    removed = []
    for match in re.finditer(r'\([^)]*\)', text):
        inner = match.group().strip('()').strip()
        if inner:
            removed.append(inner)
    text = re.sub(r'\s*\([^)]*\)', '', text).strip()
    dash_match = re.search(r'\s+-\s+', text)
    if dash_match:
        tail = text[dash_match.start():].strip().lstrip('-').strip()
        if tail:
            removed.append(tail)
        text = text[:dash_match.start()].strip()
    text = re.sub(r'\s+', ' ', text).strip()
    return text, ' | '.join(removed)


def time_to_ms(time_str):
    try:
        m, s = time_str.strip().split(":")
        return (int(m) * 60 + int(s)) * 1000
    except Exception:
        return 0


def search_qobuz(title, artist, app_id, token):
    try:
        query = f"{title} {artist}"
        url = "https://www.qobuz.com/api.json/0.2/track/search"
        params = {"query": query, "limit": 20, "app_id": app_id}
        headers = {"X-User-Auth-Token": token, "X-App-Id": app_id}
        import requests
        r = requests.get(url, params=params, headers=headers, timeout=10)
        try:
            data = r.json()
        except ValueError:
            data = {}
        if r.status_code == 401 or data.get("code") == 401:
            return None, None, "token_expired"

        tracks = data.get("tracks", {}).get("items", [])
        if not tracks:
            return None, None, "no_results"

        target_title, target_artist = title.lower().strip(), artist.lower().strip()

        def artist_match(track):
            performer = track.get("performer", {}).get("name", "").lower().strip()
            album_artist = track.get("album", {}).get("artist", {}).get("name", "").lower().strip()
            return (target_artist in performer or performer in target_artist or
                    target_artist in album_artist or album_artist in target_artist)

        for track in tracks:
            if not artist_match(track):
                continue
            t_title = track.get("title", "").lower().strip()
            if target_title in t_title or t_title in target_title:
                bit, khz = track.get("maximum_bit_depth"), track.get("maximum_sampling_rate")
                if bit and khz:
                    return int(bit), int(float(khz) * 1000), "official"

        for track in tracks:
            if not artist_match(track):
                continue
            bit, khz = track.get("maximum_bit_depth"), track.get("maximum_sampling_rate")
            if bit and khz:
                return int(bit), int(float(khz) * 1000), "official"

        return None, None, "no_artist_match"
    except Exception as e:
        return None, None, f"error: {e}"


def qobuz_enrich_thread(source_path, output_dir, default_khz, default_bit, out_name=None):
    qobuz_job.running = True
    qobuz_job.stop_flag.clear()
    cfg = load_config()
    app_id = cfg["qobuz"]["app_id"].strip() or QOBUZ_DEFAULT_APP_ID
    token = cfg["qobuz"]["token"].strip()

    try:
        with open(source_path, newline='', encoding='utf-8-sig') as f:
            rows = list(csv.DictReader(f))

        edited_rows = []
        for row in rows:
            raw_title = row.get("Song", row.get("title", "")).strip()
            raw_artist = row.get("Artist", row.get("artist", "")).strip()
            raw_album = row.get("Album", row.get("album", "")).strip()
            time_str = row.get("Duration", row.get("Time", "")).strip()
            clean_title, rem_title = clean_and_extract(raw_title)
            clean_album, rem_album = clean_and_extract(raw_album)
            edited_rows.append({
                "album": clean_album, "title": clean_title, "artist": raw_artist,
                "duration_ms": time_to_ms(time_str), "Time": time_str,
                "remaining_title": rem_title, "remaining_album": rem_album,
            })

        qobuz_job.emit("started", total=len(edited_rows))
        found = defaulted = 0
        enriched = []
        token_expired = False

        for i, row in enumerate(edited_rows):
            if qobuz_job.stop_flag.is_set():
                qobuz_job.emit("stopped")
                break
            title, artist = row["title"], row["artist"]
            first_artist = artist.split(",")[0].strip() if artist else ""
            qobuz_job.emit("track_start", index=i + 1, title=title, artist=artist)

            if not title or not token:
                row.update(max_khz=default_khz, max_bit=default_bit, quality_status="defaulted")
                defaulted += 1
            else:
                bit, khz, status = search_qobuz(title, first_artist, app_id, token)
                if status == "token_expired":
                    # Do NOT silently default every remaining track: stop and
                    # ask the user to reconnect Qobuz.
                    _mark_qobuz_expired()
                    qobuz_job.emit("token_expired", index=i + 1,
                                   message="Your Qobuz connection has expired. Reconnect Qobuz, then run again.")
                    token_expired = True
                    break
                elif bit and khz:
                    row.update(max_khz=khz, max_bit=bit, quality_status="official")
                    found += 1
                else:
                    row.update(max_khz=default_khz, max_bit=default_bit, quality_status="defaulted")
                    defaulted += 1

            qobuz_job.emit("track_done", index=i + 1, quality_status=row["quality_status"],
                            max_bit=row["max_bit"], max_khz=row["max_khz"])
            enriched.append(row)
            time.sleep(0.5)

        if token_expired:
            return  # nothing written; the UI shows the Reconnect prompt
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        out_path = Path(output_dir) / (out_name or f"playlist_enriched_{ts}.csv")
        with open(out_path, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            writer.writerow(["album", "title", "artist", "duration_ms", "Time",
                              "max_khz", "max_bit", "quality_status",
                              "remaining of title", "remaining of album"])
            for row in enriched:
                writer.writerow([row.get("album", ""), row.get("title", ""), row.get("artist", ""),
                                  row.get("duration_ms", ""), row.get("Time", ""),
                                  row.get("max_khz", ""), row.get("max_bit", ""), row.get("quality_status", ""),
                                  row.get("remaining_title", ""), row.get("remaining_album", "")])

        try:
            projects.remember(RECENT_PATH, "enriched", out_path,
                              Path(output_dir).name if out_name else Path(source_path).stem, len(enriched))
        except OSError:
            pass
        qobuz_job.emit("finished", found=found, defaulted=defaulted, output_file=str(out_path),
                       playlist_folder=str(output_dir) if out_name else None)
    except Exception as e:
        qobuz_job.emit("error", message=str(e))
    finally:
        qobuz_job.running = False


@app.route("/api/qobuz/run", methods=["POST"])
def qobuz_run():
    if qobuz_job.running:
        return jsonify({"error": "Already running"}), 400
    body = request.json or {}
    source_path = body.get("path")
    if not source_path or not os.path.exists(source_path):
        return jsonify({"error": "Source CSV not found"}), 400
    cfg = load_config()
    if cfg["qobuz"].get("token") and cfg["qobuz"].get("status") == "expired":
        return jsonify({"error": "Qobuz needs to be reconnected.", "token_expired": True}), 409
    default_khz = int(body.get("default_khz") or 48000)
    default_bit = int(body.get("default_bit") or 24)
    if body.get("output_dir"):                       # explicit override (not used by the UI)
        output_dir, out_name = body["output_dir"], None
    else:                                            # normal case: <working>\<playlist>\2_enriched.csv
        output_dir = str(projects.folder_for_input(_working_dir(), source_path))
        out_name = projects.STAGE_FILES["enriched"]
    t = threading.Thread(target=qobuz_enrich_thread,
                         args=(source_path, output_dir, default_khz, default_bit, out_name), daemon=True)
    t.start()
    return jsonify({"ok": True})


@app.route("/api/qobuz/stop", methods=["POST"])
def qobuz_stop():
    qobuz_job.stop_flag.set()
    return jsonify({"ok": True})


@app.route("/api/qobuz/events")
def qobuz_events():
    return qobuz_job.stream()


@app.route("/api/qobuz/download")
def qobuz_download():
    path = request.args.get("path")
    if not path or not os.path.exists(path):
        return jsonify({"error": "File not found"}), 404
    return send_file(path, as_attachment=True, download_name=os.path.basename(path))


# ============================================================
# DOMAIN 3 — DOWNLOADER (sldl.exe engine)
# ============================================================
DURATION_TOLERANCE = 2
ABANDON_SECS = 30
ABANDON_MB = 3
MAX_ATTEMPTS = 15   # tries per track; the never-go-lower-quality floor (set on the first pick) still applies

VERSION_KEYWORDS = ["remix", "rmx", "edit", "extended", "mix", "live",
                    "acoustic", "cover", "instrumental", "demo", "vip",
                    "bootleg", "mashup", "rework", "flip"]


def write_sldl_conf(sldl_exe_path, username, password):
    """sldl looks for sldl.conf next to the executable — write it fresh
    from Settings every run so no credential ever lives in source code."""
    conf_dir = Path(sldl_exe_path).resolve().parent
    conf_path = conf_dir / "sldl.conf"
    with open(conf_path, "w", encoding="utf-8") as f:
        f.write(f"username = {username}\npassword = {password}\n")
    return conf_path


def is_flac(file):
    return file.lower().endswith(".flac")


def duration_ok(length, target):
    return True if target is None else abs(length - target) <= DURATION_TOLERANCE


def is_unwanted_version(filename, target_title):
    fname_lower, title_lower = filename.lower(), target_title.lower()
    return any(kw in fname_lower and kw not in title_lower for kw in VERSION_KEYWORDS)


def title_in_filename(filename, target_title):
    fname_lower = re.sub(r'[^\w\s]', ' ', filename.lower())
    words = [w for w in re.sub(r'[^\w\s]', ' ', target_title.lower()).split() if w]
    return all(w in fname_lower for w in words) if words else True


def run_search(sldl_exe, query):
    cmd = [str(sldl_exe), query, "--print", "json-all", "--artist-maybe-wrong", "--search-timeout", "6000"]
    result = subprocess.run(cmd, **SUBPROC_KW, capture_output=True, text=True, encoding="utf-8", errors="ignore")
    try:
        return json.loads(result.stdout)
    except Exception:
        return []


def pick_best(results, target_sec, max_khz, max_bit, target_title, banned_peers=None, min_khz=None, min_bit=None):
    banned_peers = banned_peers or set()
    candidates = []
    for r in results:
        try:
            file = r["File"]["Filename"]
            length = int(r["File"]["Length"])
            size = int(r["File"]["Size"])
            speed = float(r["User"]["UploadSpeed"])
            username = r["User"]["Username"]
            if not is_flac(file):
                continue
            if not duration_ok(length, target_sec):
                continue
            if username in banned_peers:
                continue
            if is_unwanted_version(file, target_title):
                continue
            if not title_in_filename(file, target_title):
                continue
            file_khz, file_bit = r["File"].get("SampleRate"), r["File"].get("BitDepth")
            if file_khz and max_khz and int(file_khz) > int(max_khz):
                continue
            if file_bit and max_bit and int(file_bit) > int(max_bit):
                continue
            if file_khz and min_khz and int(file_khz) < int(min_khz):
                continue
            if file_bit and min_bit and int(file_bit) < int(min_bit):
                continue
            candidates.append({"username": username, "input": file, "size": size, "speed": speed,
                                "bit": file_bit, "khz": file_khz, "bitrate": r["File"].get("BitRate")})
        except Exception:
            continue
    if not candidates:
        return None
    candidates.sort(key=lambda x: (x["size"], x["speed"]), reverse=True)
    return candidates[0]


def download_with_monitor(sldl_exe, music_vault, username, file_input, max_khz=None, max_bit=None, min_khz=None, min_bit=None):
    slsk_uri = f"slsk://{username}/{file_input}"
    cmd = [str(sldl_exe), slsk_uri, "--path", str(music_vault), "--strict-conditions", "--strict-title",
           "--max-stale-time", str(ABANDON_SECS * 1000)]
    if max_khz: cmd += ["--max-samplerate", str(max_khz)]
    if max_bit: cmd += ["--max-bitdepth", str(max_bit)]
    if min_khz: cmd += ["--min-samplerate", str(min_khz)]
    if min_bit: cmd += ["--min-bitdepth", str(min_bit)]

    process = subprocess.Popen(cmd, **SUBPROC_KW, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, encoding="utf-8", errors="ignore")
    output_lines, result_flag = [], {"status": "failed"}

    def reader():
        for line in process.stdout:
            output_lines.append(line)
        if "Succeeded" in "".join(output_lines):
            result_flag["status"] = "success"

    t = threading.Thread(target=reader, daemon=True)
    t.start()
    start_time = time.time()
    while time.time() - start_time < ABANDON_SECS:
        if process.poll() is not None:
            break
        time.sleep(1)

    if process.poll() is None:
        downloaded_mb = 0
        for line in output_lines:
            m = re.search(r'InProgress \(([0-9.]+)MB\)', line)
            if m:
                downloaded_mb = max(downloaded_mb, float(m.group(1)))
        if downloaded_mb < ABANDON_MB:
            process.kill()
            process.wait()
            for f in Path(music_vault).rglob("*.incomplete"):
                try:
                    f.unlink()
                except Exception:
                    pass
            return "abandoned"

    t.join()
    process.wait()
    return result_flag["status"]


def downloader_engine_thread(csv_path, out_dir=None):
    downloader_job.running = True
    downloader_job.stop_flag.clear()
    cfg = load_config()
    sldl_exe = resolve_tool_path(cfg, "sldl_exe", "sldl.exe")
    music_vault = cfg["paths"]["music_vault"]
    username = cfg["soulseek"]["username"]
    password = cfg["soulseek"]["password"]

    if not sldl_exe or not os.path.exists(sldl_exe):
        downloader_job.emit("error", message="Mucify's bundled downloader (sldl.exe) is missing - please reinstall Mucify.")
        downloader_job.running = False
        return
    if not music_vault:
        downloader_job.emit("error", message="Music library folder is not set - open Settings.")
        downloader_job.running = False
        return
    Path(music_vault).mkdir(parents=True, exist_ok=True)
    if username and password:
        write_sldl_conf(sldl_exe, username, password)

    total_done = total_failed = total_skipped = 0
    slow_skipped_songs = []
    report_rows = []
    rows, input_fieldnames = [], []
    stopped_early = False

    try:
        with open(csv_path, newline='', encoding='utf-8-sig') as f:
            rows = list(csv.DictReader(f))
            input_fieldnames = list(rows[0].keys()) if rows else []

        downloader_job.emit("started", total=len(rows))

        for i, row in enumerate(rows):
            if downloader_job.stop_flag.is_set():
                downloader_job.emit("stopped")
                stopped_early = True
                break

            title = row.get("title", "").strip()
            artist = row.get("artist", "").strip()
            album = row.get("album", "").strip()
            duration_ms = row.get("duration_ms", "0")
            max_khz_raw = row.get("max_khz", "").strip()
            max_bit_raw = row.get("max_bit", "").strip()
            card_id = f"card_{i}"
            report_row = dict(row)

            if not title:
                total_skipped += 1
                report_row.update(result="skipped_missing_fields", found_bit="", found_khz="",
                                   quality_mismatch="", attempts_used=0)
                report_rows.append(report_row)
                continue

            try:
                target_sec = int(int(duration_ms) / 1000) or None
            except Exception:
                target_sec = None
            try:
                max_khz = int(max_khz_raw) if max_khz_raw else None
                max_bit = int(max_bit_raw) if max_bit_raw else None
            except Exception:
                max_khz = max_bit = None

            artist_parts = [a.strip() for a in artist.split(",") if a.strip()] if artist else []
            queries_to_try, seen = [], set()

            def add_q(q):
                q = q.strip()
                if q and q.lower() not in seen:
                    queries_to_try.append(q)
                    seen.add(q.lower())

            if album and album.lower() != title.lower():
                add_q(f"{album} {title}")
            for art in artist_parts:
                add_q(f"{art} {title}")
            add_q(title)

            results, used_query = [], queries_to_try[0] if queries_to_try else title
            for q in queries_to_try:
                r = run_search(sldl_exe, q)
                if pick_best(r, target_sec, max_khz, max_bit, title, set()):
                    results, used_query = r, q
                    break

            downloader_job.emit("card_searching", id=card_id, title=title, artist=artist,
                                 query=used_query, index=i + 1, total=len(rows))

            banned_peers, min_khz_floor, min_bit_floor = set(), None, None
            had_abandon = had_genuine_fail = False
            row_result, winning_candidate, attempts_used = None, None, 0

            for attempt in range(MAX_ATTEMPTS):
                attempts_used = attempt + 1
                best = pick_best(results, target_sec, max_khz, max_bit, title, banned_peers, min_khz_floor, min_bit_floor)
                if not best:
                    row_result = "all_downloads_failed" if had_genuine_fail else ("skipped_slow" if had_abandon else "no_result")
                    break
                if attempt == 0:
                    if best["khz"]: min_khz_floor = int(best["khz"])
                    if best["bit"]: min_bit_floor = int(best["bit"])

                bit_info = f"{best['bit']}bit" if best['bit'] else "?bit"
                khz_info = f"{int(best['khz'])/1000:.1f}kHz" if best['khz'] else "?kHz"
                size_mb = round(best['size'] / 1024 / 1024, 2)
                downloader_job.emit("card_downloading", id=card_id, quality=f"[{bit_info}/{khz_info}]",
                                     size=f"{size_mb} MB", speed=round(best['speed'], 2),
                                     peer=best['username'], attempt=attempt + 1, max_attempts=MAX_ATTEMPTS)

                status = download_with_monitor(sldl_exe, music_vault, best["username"], best["input"],
                                                max_khz, max_bit, min_khz_floor, min_bit_floor)
                if status == "success":
                    row_result, winning_candidate = "success", best
                    break
                elif status == "abandoned":
                    had_abandon = True
                    banned_peers.add(best["username"])
                    downloader_job.emit("card_retrying", id=card_id, reason="slow_peer", attempt=attempt + 1, max_attempts=MAX_ATTEMPTS)
                else:
                    had_genuine_fail = True
                    banned_peers.add(best["username"])
                    downloader_job.emit("card_retrying", id=card_id, reason="download_failed", attempt=attempt + 1, max_attempts=MAX_ATTEMPTS)
            else:
                row_result = "all_downloads_failed" if had_genuine_fail else ("skipped_slow" if had_abandon else "no_result")

            if row_result == "success":
                total_done += 1
                downloader_job.emit("card_done", id=card_id)
                report_row.update(result="success", found_bit=winning_candidate["bit"] or "",
                                   found_khz=winning_candidate["khz"] or "",
                                   quality_mismatch=bool(
                                       (max_bit and winning_candidate["bit"] and int(winning_candidate["bit"]) < int(max_bit)) or
                                       (max_khz and winning_candidate["khz"] and int(winning_candidate["khz"]) < int(max_khz))),
                                   attempts_used=attempts_used)
            else:
                total_failed += 1 if row_result == "all_downloads_failed" else 0
                total_skipped += 1 if row_result in ("no_result", "skipped_slow") else 0
                reason_label = {"no_result": "No match found", "skipped_slow": "All peers too slow",
                                 "all_downloads_failed": "All download attempts failed"}.get(row_result, row_result)
                downloader_job.emit("card_failed", id=card_id, reason=reason_label)
                report_row.update(result=row_result, found_bit="", found_khz="", quality_mismatch="", attempts_used=attempts_used)
                if row_result == "skipped_slow":
                    slow_skipped_songs.append({"title": title, "artist": artist})

            report_rows.append(report_row)
            downloader_job.emit("stats", done=total_done, failed=total_failed, skipped=total_skipped)

    except Exception as e:
        downloader_job.emit("error", message=str(e))

    # ---- save the playlist's results: 3_skipped.csv (everything NOT downloaded) and 4_successful.csv
    playlist_folder = None
    skipped_count = success_count = 0
    try:
        playlist_folder = Path(out_dir) if out_dir else projects.folder_for_input(_working_dir(), csv_path)
        playlist_folder.mkdir(parents=True, exist_ok=True)
        extra_cols = ["result", "found_bit", "found_khz", "quality_mismatch", "attempts_used"]
        fieldnames = input_fieldnames + [c for c in extra_cols if c not in input_fieldnames]

        success_rows = [r for r in report_rows if r.get("result") == "success"]
        skipped_rows = [r for r in report_rows if r.get("result") != "success"]
        for r in rows[len(report_rows):]:            # never attempted (stopped / interrupted)
            skipped_rows.append({**r, "result": "not_attempted", "found_bit": "", "found_khz": "",
                                 "quality_mismatch": "", "attempts_used": 0})

        success_path = projects.stage_path(playlist_folder, "successful")
        skipped_path = projects.stage_path(playlist_folder, "skipped")
        rerun_of_skipped = Path(csv_path).name == projects.STAGE_FILES["skipped"]

        if rerun_of_skipped:                          # keep what earlier runs already got
            s_fields, s_rows = projects.merge_successful(success_path, success_rows, fieldnames)
        else:
            s_fields, s_rows = fieldnames, success_rows
        if s_rows:
            projects.write_rows(success_path, s_fields, s_rows)
        elif success_path.exists():
            success_path.unlink()                     # stale list from an older run
        if skipped_rows:
            projects.write_rows(skipped_path, fieldnames, skipped_rows)
        elif skipped_path.exists():
            skipped_path.unlink()
        success_count, skipped_count = len(s_rows), len(skipped_rows)

        if total_done > 0:
            projects.remember(RECENT_PATH, "downloaded", music_vault, playlist_folder.name, total_done)
    except Exception as e:
        downloader_job.emit("error", message=f"Couldn't save the playlist lists: {e}")

    downloader_job.running = False
    downloader_job.emit("finished", done=total_done, failed=total_failed, skipped=total_skipped, slow_skipped=slow_skipped_songs,
                        playlist_folder=str(playlist_folder) if playlist_folder else None,
                        successful_count=success_count, not_downloaded_count=skipped_count)


@app.route("/api/downloader/start", methods=["POST"])
def downloader_start():
    if downloader_job.running:
        return jsonify({"error": "Already running"}), 400
    csv_path = (request.json or {}).get("path")
    if not csv_path or not os.path.exists(csv_path):
        return jsonify({"error": "Enriched CSV not found"}), 400
    t = threading.Thread(target=downloader_engine_thread, args=(csv_path,), daemon=True)
    t.start()
    return jsonify({"ok": True})


@app.route("/api/downloader/stop", methods=["POST"])
def downloader_stop():
    downloader_job.stop_flag.set()
    return jsonify({"ok": True})


@app.route("/api/downloader/events")
def downloader_events():
    return downloader_job.stream()


# ============================================================
# DOMAIN 4 — POST-PROCESSING (ReplayGain via rsgain)
# ============================================================
def get_album_key(flac_path):
    from mutagen.flac import FLAC
    try:
        audio = FLAC(flac_path)
    except Exception:
        return None
    album = audio.get("album", [""])[0].strip()
    albumartist = audio.get("albumartist", audio.get("artist", [""]))[0].strip()
    return (albumartist.lower(), album.lower()) if album else None


def postprocess_thread(library_root, rsgain_exe):
    postprocess_job.running = True
    postprocess_job.stop_flag.clear()
    try:
        root = Path(library_root)
        postprocess_job.emit("log", message=f"Scanning {root} for FLAC files...")
        flac_files = list(root.rglob("*.flac"))
        postprocess_job.emit("log", message=f"Found {len(flac_files)} FLAC files.")

        groups = defaultdict(list)
        orphans = []
        for f in flac_files:
            key = get_album_key(f)
            (orphans if key is None else groups[key]).append(f) if key is None else groups[key].append(f)

        real_albums = {}
        for key, files in groups.items():
            if len(files) >= 2:
                real_albums[key] = files
            else:
                orphans.extend(files)

        postprocess_job.emit("started", albums=len(real_albums), orphans=len(orphans))

        for i, ((artist, album), files) in enumerate(real_albums.items(), 1):
            if postprocess_job.stop_flag.is_set():
                postprocess_job.emit("stopped")
                postprocess_job.running = False
                return
            postprocess_job.emit("log", message=f"[{i}/{len(real_albums)}] Album: {album} ({artist}) — {len(files)} tracks")
            cmd = [rsgain_exe, "custom", "-a", "-s", "i"] + [str(f) for f in files]
            result = subprocess.run(cmd, **SUBPROC_KW, capture_output=True, text=True, encoding="utf-8", errors="replace")
            if result.returncode != 0:
                postprocess_job.emit("log", message=f"  [ERROR] {result.stderr.strip()}")
            postprocess_job.emit("progress", done=i, total=len(real_albums))

        if orphans:
            postprocess_job.emit("log", message=f"Processing {len(orphans)} orphan tracks (track gain only)...")
            chunk_size = 200
            for i in range(0, len(orphans), chunk_size):
                chunk = orphans[i:i + chunk_size]
                cmd = [rsgain_exe, "custom", "-s", "i"] + [str(f) for f in chunk]
                result = subprocess.run(cmd, **SUBPROC_KW, capture_output=True, text=True, encoding="utf-8", errors="replace")
                if result.returncode != 0:
                    postprocess_job.emit("log", message=f"  [ERROR] {result.stderr.strip()}")

        postprocess_job.emit("finished", albums=len(real_albums), orphans=len(orphans))
    except Exception as e:
        postprocess_job.emit("error", message=str(e))
    finally:
        postprocess_job.running = False


@app.route("/api/postprocess/run", methods=["POST"])
def postprocess_run():
    if postprocess_job.running:
        return jsonify({"error": "Already running"}), 400
    body = request.json or {}
    library_root = body.get("path")
    cfg = load_config()
    rsgain_exe = resolve_tool_path(cfg, "rsgain_exe", "rsgain.exe")
    if not library_root or not os.path.isdir(library_root):
        return jsonify({"error": "Library folder not found"}), 400
    if not rsgain_exe or not os.path.exists(rsgain_exe):
        return jsonify({"error": "Mucify's bundled ReplayGain tool (rsgain.exe) is missing - please reinstall Mucify."}), 400
    t = threading.Thread(target=postprocess_thread, args=(library_root, rsgain_exe), daemon=True)
    t.start()
    return jsonify({"ok": True})


@app.route("/api/postprocess/stop", methods=["POST"])
def postprocess_stop():
    postprocess_job.stop_flag.set()
    return jsonify({"ok": True})


@app.route("/api/postprocess/events")
def postprocess_events():
    return postprocess_job.stream()


# ============================================================
# STATIC / LANDING PAGE
# ============================================================
@app.route("/")
def index():
    return send_from_directory(str(paths.templates_dir()), "index.html")


@app.route("/static/<path:filename>")
def static_files(filename):
    return send_from_directory(str(paths.static_dir()), filename)


@app.route("/api/ping")
def ping():
    return jsonify({"ok": True})
