# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 mageman007 and contributors
"""
Qobuz connection for Mucify.

connect flow (start_connect):
  1. open a Mucify-owned window on https://play.qobuz.com/login
  2. every ~1.5 s run a small probe inside that page which
       a) hooks fetch()/XMLHttpRequest to catch the X-User-Auth-Token header
          the web player sends, and
       b) scans localStorage for a token-looking value
  3. every candidate is checked against the Qobuz API; the first one Qobuz
     accepts is saved through `on_token` and the window closes.

!! The probe was written from how the web player is known to behave and could
!! NOT be tested end-to-end yet. If Qobuz changes where it keeps the token,
!! only PROBE_JS / _candidates() need adjusting. The manual-paste fallback in
!! the UI (/api/qobuz/token) always works independently of this module.
"""
import json
import threading
import time

import requests

from . import host

DEFAULT_APP_ID = "798273057"
LOGIN_URL = "https://play.qobuz.com/login"
API_BASE = "https://www.qobuz.com/api.json/0.2"
POLL_SECONDS = 1.5
TIMEOUT_SECONDS = 15 * 60

PROBE_JS = r"""
(function(){
 try{
  if(!window.__mucify){
    window.__mucify={tok:null};
    var note=function(h){ try{ if(!h) return; var t=null;
        if(typeof h.get==='function'){ t=h.get('X-User-Auth-Token')||h.get('x-user-auth-token'); }
        else if(Array.isArray(h)){ for(var i=0;i<h.length;i++){ if(String(h[i][0]).toLowerCase()==='x-user-auth-token') t=h[i][1]; } }
        else { for(var k in h){ if(k.toLowerCase()==='x-user-auth-token') t=h[k]; } }
        if(t) window.__mucify.tok=String(t);
      }catch(e){} };
    var of=window.fetch;
    if(of){ window.fetch=function(input,init){ try{ note(init&&init.headers); if(input&&input.headers) note(input.headers);}catch(e){} return of.apply(this,arguments); }; }
    var xo=XMLHttpRequest.prototype.setRequestHeader;
    XMLHttpRequest.prototype.setRequestHeader=function(k,v){ try{ if(String(k).toLowerCase()==='x-user-auth-token') window.__mucify.tok=String(v);}catch(e){} return xo.apply(this,arguments); };
  }
  var out={hook:window.__mucify.tok,host:location.hostname,ls:[],uid:null};
  var ok=function(v){ return typeof v==='string' && v.length>=20 && v.length<=300 && /^[A-Za-z0-9_\-\.=]+$/.test(v); };
  var found=[];
  var walk=function(o,depth,name){
    if(o===null||o===undefined||depth>4) return;
    if(typeof o==='string'){ if(/token/i.test(name||'') && ok(o)) found.push(o); return; }
    if(typeof o==='object'){ for(var k in o){ walk(o[k],depth+1,k); } }
  };
  for(var i=0;i<localStorage.length;i++){
    var key=localStorage.key(i), val=localStorage.getItem(key);
    if(!val) continue;
    var parsed=null; try{ parsed=JSON.parse(val); }catch(e){}
    if(parsed!==null && typeof parsed==='object'){
      if(/user/i.test(key) && (parsed.id||parsed.user_id)) out.uid=String(parsed.id||parsed.user_id);
      walk(parsed,0,key);
    } else if(/token/i.test(key)){ var raw=(typeof parsed==='string')?parsed:val; if(ok(raw)) found.push(raw); }
  }
  out.ls=found.filter(function(v,i,a){return a.indexOf(v)===i;}).slice(0,8);
  return JSON.stringify(out);
 }catch(e){ return JSON.stringify({err:String(e)}); }
})()
"""

_lock = threading.Lock()
_state = {"state": "idle", "message": "", "vpn_hint": False}
_window = None
_cancel = threading.Event()


# ------------------------------------------------------------------ API check
def validate_token(token: str, app_id: str = DEFAULT_APP_ID, timeout: float = 10.0) -> str:
    """-> "ok" | "invalid" | "unknown" (network trouble / unexpected answer).
    Uses an endpoint that REQUIRES a user token, so a random string can't pass."""
    try:
        r = requests.get(f"{API_BASE}/favorite/getUserFavorites",
                         params={"type": "tracks", "limit": 1, "app_id": app_id},
                         headers={"X-User-Auth-Token": token, "X-App-Id": app_id}, timeout=timeout)
        if r.status_code in (401, 403):
            return "invalid"
        try:
            code = r.json().get("code")
        except ValueError:
            code = None
        if code in (401, 403):
            return "invalid"
        if r.status_code == 200:
            return "ok"
        return "unknown"
    except requests.RequestException:
        return "unknown"


def site_reachable(timeout: float = 6.0) -> bool:
    try:
        return requests.get("https://play.qobuz.com/", timeout=timeout).status_code < 500
    except requests.RequestException:
        return False


# ------------------------------------------------------------------ state
def _set(**kw):
    with _lock:
        _state.update(kw)


def connect_status() -> dict:
    with _lock:
        return dict(_state)


def cancel_connect():
    _cancel.set()
    w = _window
    if w is not None:
        try:
            w.destroy()
        except Exception:
            pass
    _set(state="idle", message="")


def _candidates(probe: dict):
    """Ordered (token, trusted) pairs. 'trusted' = seen in a real request header."""
    out = []
    if probe.get("hook"):
        out.append((probe["hook"], True))
    for t in probe.get("ls", []) or []:
        if (t, True) not in out and (t, False) not in out:
            out.append((t, False))
    return out


def start_connect(on_token):
    global _window
    with _lock:
        if _state["state"] == "waiting":
            return dict(_state)
        _state.update(state="waiting", message="Log in to Qobuz in the window that just opened. "
                                               "Mucify will pick up the connection automatically.",
                      vpn_hint=False)
    if not host.available():
        _set(state="failed", message="The Qobuz login window is only available in the installed Mucify app. "
                                     "Use the manual token option below.")
        return connect_status()
    _cancel.clear()
    threading.Thread(target=_run, args=(on_token,), daemon=True).start()
    return connect_status()


def _run(on_token):
    global _window
    wv = host.webview_module()
    closed = threading.Event()
    try:
        if not site_reachable():
            _set(vpn_hint=True)
        win = wv.create_window("Connect Qobuz", LOGIN_URL, width=1040, height=780, min_size=(640, 520))
        _window = win
        win.events.closed += lambda *a: closed.set()
        deadline = time.time() + TIMEOUT_SECONDS
        blank_polls = 0
        while time.time() < deadline and not closed.is_set() and not _cancel.is_set():
            time.sleep(POLL_SECONDS)
            try:
                raw = win.evaluate_js(PROBE_JS)
                probe = json.loads(raw) if raw else {}
            except Exception:
                blank_polls += 1
                if blank_polls == 8:           # ~12 s without a usable page
                    _set(vpn_hint=True)
                continue
            if probe.get("host", "").endswith("qobuz.com") is False:
                blank_polls += 1
                if blank_polls >= 8:
                    _set(vpn_hint=True)
                continue
            for token, trusted in _candidates(probe):
                verdict = validate_token(token)
                if verdict == "ok" or (trusted and verdict == "unknown"):
                    on_token(token, user_id=probe.get("uid"))
                    _set(state="connected", message="Qobuz connected.")
                    try:
                        win.destroy()
                    except Exception:
                        pass
                    return
        if _state["state"] == "waiting":
            _set(state="failed", message=(
                "Mucify couldn't detect your Qobuz login automatically. "
                "Use the manual token option below - it only takes a minute."))
    except Exception as e:
        _set(state="failed", message=f"Couldn't open the Qobuz login window ({e}). Use the manual token option below.")
    finally:
        _window = None
