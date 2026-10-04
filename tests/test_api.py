# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 mageman007 and contributors
import csv
import json
import os
import unittest
from unittest import mock

from tests.helpers import HDR, backend, paths
from mucify import qobuz_auth


class FakeResp:
    def __init__(self, status=200, body=None):
        self.status_code = status
        self._body = body if body is not None else {}

    def json(self):
        return self._body


class ApiTests(unittest.TestCase):
    def setUp(self):
        if backend.CONFIG_PATH.exists():
            backend.CONFIG_PATH.unlink()
        self.c = backend.app.test_client()

    # ---- local-only protection
    def test_guard(self):
        self.assertEqual(self.c.post("/api/settings", json={}).status_code, 403)
        self.assertEqual(self.c.post("/api/settings", json={}, headers=HDR).status_code, 200)
        self.assertEqual(self.c.get("/api/ping", headers={"Host": "evil.example"}).status_code, 403)
        self.assertEqual(self.c.get("/api/ping", headers={"Host": "127.0.0.1:5123"}).status_code, 200)

    # ---- first run
    def test_first_run_flow_creates_default_folders(self):
        st = self.c.get("/api/setup/state").get_json()
        self.assertFalse(st["first_run_done"])
        self.assertTrue(st["tools"]["sldl"] and st["tools"]["rsgain"])
        self.assertTrue(st["defaults"]["music_vault"].endswith("Mucify"))
        r = self.c.post("/api/setup/complete", json={"username": "u_1", "password": "p"}, headers=HDR)
        self.assertEqual(r.status_code, 200)
        cfg = self.c.get("/api/settings").get_json()
        self.assertTrue(os.path.isdir(cfg["paths"]["music_vault"]))
        self.assertTrue(os.path.isdir(cfg["paths"]["working_dir"]))
        self.assertEqual(cfg["soulseek"]["username"], "u_1")
        self.assertTrue(self.c.get("/api/setup/state").get_json()["first_run_done"])

    def test_tools_resolve_to_bundled_copies(self):
        d = self.c.get("/api/settings").get_json()["detected"]
        self.assertTrue(d["sldl_exe"].endswith("sldl.exe") and os.path.exists(d["sldl_exe"]))
        self.assertTrue(d["rsgain_exe"].endswith("rsgain.exe"))

    # ---- Qobuz
    def test_manual_token_validation(self):
        with mock.patch.object(qobuz_auth.requests, "get", return_value=FakeResp(401, {"code": 401})):
            r = self.c.post("/api/qobuz/token", json={"token": "bad"}, headers=HDR)
            self.assertEqual(r.status_code, 400)
        with mock.patch.object(qobuz_auth.requests, "get", return_value=FakeResp(200, {"tracks": {}})):
            r = self.c.post("/api/qobuz/token", json={"token": "good"}, headers=HDR)
            self.assertEqual(r.status_code, 200)
        q = self.c.get("/api/settings").get_json()["qobuz"]
        self.assertEqual((q["token"], q["status"]), ("good", "ok"))

    def test_expired_token_stops_enrichment_and_asks_to_reconnect(self):
        self.c.post("/api/settings", json={"qobuz": {"token": "old"}}, headers=HDR)
        src = paths.user_data_dir() / "in.csv"
        with open(src, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f); w.writerow(["Song", "Artist", "Album", "Time"])
            w.writerows([["One", "A", "X", "3:00"], ["Two", "B", "Y", "3:10"]])
        out = paths.user_data_dir() / "out"
        while not backend.qobuz_job.queue.empty():
            backend.qobuz_job.queue.get()
        with mock.patch("requests.get", return_value=FakeResp(401, {"code": 401, "message": "Invalid or missing user_auth_token"})):
            backend.qobuz_enrich_thread(str(src), str(out), 48000, 24)
        events = []
        while not backend.qobuz_job.queue.empty():
            events.append(backend.qobuz_job.queue.get()["type"])
        self.assertIn("token_expired", events)
        self.assertNotIn("finished", events)                      # no silent fallback for the remaining tracks
        self.assertFalse(out.exists() and any(out.iterdir()))     # nothing written
        self.assertEqual(self.c.get("/api/settings").get_json()["qobuz"]["status"], "expired")
        r = self.c.post("/api/qobuz/run", json={"path": str(src)}, headers=HDR)
        self.assertEqual(r.status_code, 409)
        self.assertTrue(r.get_json()["token_expired"])
        # reconnecting (new token) clears the expired state
        self.c.post("/api/settings", json={"qobuz": {"token": "fresh"}}, headers=HDR)
        self.assertEqual(self.c.get("/api/settings").get_json()["qobuz"]["status"], "ok")

    def test_no_token_still_defaults_to_24_48(self):
        src = paths.user_data_dir() / "in2.csv"
        with open(src, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f); w.writerow(["Song", "Artist", "Album", "Time"]); w.writerow(["One", "A", "X", "3:00"])
        out = paths.user_data_dir() / "out2"
        out.mkdir(exist_ok=True)
        backend.qobuz_enrich_thread(str(src), str(out), 48000, 24)
        files = list(out.glob("playlist_enriched_*.csv"))
        self.assertEqual(len(files), 1)
        rows = list(csv.DictReader(open(files[0], encoding="utf-8-sig")))
        self.assertEqual((rows[0]["max_khz"], rows[0]["max_bit"], rows[0]["quality_status"]), ("48000", "24", "defaulted"))

    def test_open_url_only_https(self):
        self.assertEqual(self.c.post("/api/open-url", json={"url": "file:///c:/x"}, headers=HDR).status_code, 400)

    def test_connect_without_window_reports_failure_and_manual_path(self):
        r = self.c.post("/api/qobuz/connect", headers=HDR).get_json()
        self.assertEqual(r["state"], "failed")


class QobuzProbeLogicTests(unittest.TestCase):
    def test_candidates_prefers_header_seen_in_requests(self):
        c = qobuz_auth._candidates({"hook": "AAA", "ls": ["BBB", "AAA"]})
        self.assertEqual(c[0], ("AAA", True))
        self.assertIn(("BBB", False), c)
        self.assertEqual(len(c), 2)


if __name__ == "__main__":
    unittest.main()


class ProbeSimulationTest(unittest.TestCase):
    def test_probe_js_in_node(self):
        import shutil, subprocess
        node = shutil.which("node")
        if not node:
            self.skipTest("node not installed")
        here = os.path.dirname(__file__)
        r = subprocess.run([node, os.path.join(here, "probe_sim.js"), qobuz_auth.__file__],
                           capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("PROBE SIM OK", r.stdout)
        self.assertNotIn("Assertion failed", r.stderr)
