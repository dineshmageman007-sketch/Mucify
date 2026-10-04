# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 mageman007 and contributors
import socket
import struct
import threading
import unittest

import tests.helpers  # noqa: F401
from mucify import soulseek


def _pack_str(s):
    b = s.encode()
    return struct.pack("<I", len(b)) + b


class FakeServer:
    """Minimal Soulseek server: answers the login message with success or a failure reason."""

    def __init__(self, reply):
        self.reply = reply
        self.received = None
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(1)
        self.port = self.sock.getsockname()[1]
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        conn, _ = self.sock.accept()
        self.sock.close()
        with conn:
            head = conn.recv(4)
            (n,) = struct.unpack("<I", head)
            data = b""
            while len(data) < n:
                data += conn.recv(n - len(data))
            self.received = data
            if self.reply == "close":
                return
            if self.reply == "ok":
                payload = b"\x01" + _pack_str("Welcome to Soulseek") + struct.pack("<I", 0x7F000001) + _pack_str("x") + b"\x00"
            else:
                payload = b"\x00" + _pack_str(self.reply)
            body = struct.pack("<I", 1) + payload
            conn.sendall(struct.pack("<I", len(body)) + body)


class SoulseekTests(unittest.TestCase):
    def test_random_credentials(self):
        self.assertRegex(soulseek.random_username(), r"^[a-z]+_[a-z]+_\d{4}$")
        pw = soulseek.random_password()
        self.assertEqual(len(pw), 16)
        self.assertNotEqual(pw, soulseek.random_password())

    def test_login_message_layout(self):
        msg = soulseek.build_login_message("bob", "pw")
        (length,) = struct.unpack("<I", msg[:4])
        self.assertEqual(length, len(msg) - 4)
        self.assertEqual(struct.unpack("<I", msg[4:8])[0], 1)          # code 1 = Login
        self.assertEqual(msg[8:15], struct.pack("<I", 3) + b"bob")
        import hashlib
        self.assertIn(hashlib.md5(b"bobpw").hexdigest().encode(), msg)

    def test_success(self):
        srv = FakeServer("ok")
        r = soulseek.test_login("newuser", "secret", host="127.0.0.1", port=srv.port, timeout=3)
        self.assertTrue(r["ok"], r)
        self.assertIn(b"newuser", srv.received)

    def test_wrong_password_message(self):
        srv = FakeServer("INVALIDPASS")
        r = soulseek.test_login("taken", "nope", host="127.0.0.1", port=srv.port, timeout=3)
        self.assertFalse(r["ok"])
        self.assertEqual(r["reason"], "INVALIDPASS")
        self.assertIn("🎲", r["message"])

    def test_server_closes(self):
        srv = FakeServer("close")
        r = soulseek.test_login("a", "b", host="127.0.0.1", port=srv.port, timeout=3)
        self.assertFalse(r["ok"])

    def test_unreachable_and_empty(self):
        s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
        self.assertFalse(soulseek.test_login("a", "b", host="127.0.0.1", port=port, timeout=2)["ok"])
        self.assertEqual(soulseek.test_login("", "x")["reason"], "EMPTY")


if __name__ == "__main__":
    unittest.main()
