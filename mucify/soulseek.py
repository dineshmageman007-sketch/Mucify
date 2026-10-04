# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 mageman007 and contributors
"""
Soulseek helpers: random credentials + a real login test.

The login test speaks the Soulseek server protocol directly (message code 1),
so it works without sldl.exe and does not depend on any sldl version.
Soulseek creates an account automatically the first time an unused username
logs in; if the name already exists the server answers INVALIDPASS.
"""
import hashlib
import secrets
import socket
import string
import struct

SERVER_HOST = "server.slsknet.org"
SERVER_PORT = 2242
CLIENT_VERSION = 160
CLIENT_MINOR = 1

_ADJECTIVES = ["amber", "brisk", "calm", "crisp", "dusty", "eager", "fuzzy", "gentle", "hazy", "lucid",
               "mellow", "nimble", "quiet", "rapid", "silent", "sunny", "velvet", "vivid", "witty", "zesty"]
_NOUNS = ["otter", "falcon", "comet", "harbor", "lantern", "meadow", "nebula", "orchid", "pebble", "quartz",
          "raven", "saffron", "tundra", "violin", "willow", "zephyr", "echo", "ember", "fjord", "grove"]
_PW_ALPHABET = "".join(c for c in string.ascii_letters + string.digits if c not in "O0Il1")


def random_username() -> str:
    return f"{secrets.choice(_ADJECTIVES)}_{secrets.choice(_NOUNS)}_{secrets.randbelow(9000) + 1000}"


def random_password(length: int = 16) -> str:
    return "".join(secrets.choice(_PW_ALPHABET) for _ in range(length))


# ------------------------------------------------------------ wire format
def _pack_str(s: str) -> bytes:
    b = s.encode("utf-8")
    return struct.pack("<I", len(b)) + b


def build_login_message(username: str, password: str) -> bytes:
    digest = hashlib.md5((username + password).encode("utf-8")).hexdigest()
    payload = (_pack_str(username) + _pack_str(password) + struct.pack("<I", CLIENT_VERSION)
               + _pack_str(digest) + struct.pack("<I", CLIENT_MINOR))
    body = struct.pack("<I", 1) + payload          # message code 1 = Login
    return struct.pack("<I", len(body)) + body


def _recv_exact(sock, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("Soulseek server closed the connection")
        buf += chunk
    return buf


def read_message(sock):
    (length,) = struct.unpack("<I", _recv_exact(sock, 4))
    if length < 4 or length > 5_000_000:
        raise ValueError("Unexpected data from server")
    data = _recv_exact(sock, length)
    return struct.unpack("<I", data[:4])[0], data[4:]


def parse_login_response(payload: bytes):
    """-> (success: bool, text: str)  text = greeting on success, reason on failure."""
    success = payload[0] == 1
    (slen,) = struct.unpack("<I", payload[1:5])
    return success, payload[5:5 + slen].decode("utf-8", "replace")


_FAIL_MESSAGES = {
    "INVALIDPASS": "That username already exists on Soulseek with a different password. "
                   "Press the 🎲 button for a new username, or enter the correct password.",
    "INVALIDUSERNAME": "Soulseek doesn't accept that username. Try a shorter one with only "
                       "letters, numbers and underscores (or press 🎲).",
    "SVRFULL": "The Soulseek server is full right now. Try again in a minute.",
    "SVRPRIVATE": "The Soulseek server is currently private. Try again later.",
}


def test_login(username: str, password: str, host: str = SERVER_HOST, port: int = SERVER_PORT,
               timeout: float = 12.0) -> dict:
    """Returns {"ok": bool, "message": str, "reason": str}."""
    username = (username or "").strip()
    if not username or not password:
        return {"ok": False, "reason": "EMPTY", "message": "Enter a username and a password first."}
    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            sock.settimeout(timeout)
            sock.sendall(build_login_message(username, password))
            for _ in range(5):                       # skip any unrelated messages
                code, payload = read_message(sock)
                if code == 1:
                    ok, text = parse_login_response(payload)
                    if ok:
                        return {"ok": True, "reason": "", "message":
                                f"Connected to Soulseek as “{username}”. "
                                "(If the name was new, the account was created for you.)"}
                    return {"ok": False, "reason": text,
                            "message": _FAIL_MESSAGES.get(text, f"Soulseek refused the login ({text or 'unknown reason'}).")}
            return {"ok": False, "reason": "NO_REPLY", "message": "Soulseek didn't answer the login. Try again."}
    except (socket.timeout, TimeoutError):
        return {"ok": False, "reason": "TIMEOUT", "message":
                "Timed out talking to the Soulseek server. Check your internet connection or firewall and try again."}
    except OSError as e:
        return {"ok": False, "reason": "NETWORK", "message":
                f"Couldn't reach the Soulseek server ({e}). Check your internet connection or firewall."}
    except Exception as e:  # malformed reply etc.
        return {"ok": False, "reason": "ERROR", "message": f"Unexpected response from Soulseek: {e}"}
