# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 mageman007 and contributors
import unittest
from unittest import mock

from tests.helpers import HDR, backend, paths
from mucify import host, winstate

ONE = [(0, 0, 1920, 1080)]
TWO = [(0, 0, 1920, 1080), (1920, 0, 3840, 1080)]


class WindowStateTests(unittest.TestCase):
    def setUp(self):
        f = winstate.state_file()
        if f.exists():
            f.unlink()

    def test_roundtrip_and_corrupt_file(self):
        st = {"x": 100, "y": 50, "w": 1300, "h": 800, "maximized": True}
        self.assertTrue(winstate.save(st))
        self.assertEqual(winstate.load(), st)
        winstate.state_file().write_text("{ not json")
        self.assertIsNone(winstate.load())

    def test_normalize_accepts_good_state(self):
        st = {"x": 100, "y": 50, "w": 1300, "h": 800, "maximized": False}
        self.assertEqual(winstate.normalize(st, ONE), st)

    def test_off_screen_position_is_ignored(self):
        st = {"x": 2200, "y": 100, "w": 1300, "h": 800, "maximized": False}      # was on a 2nd monitor
        self.assertIsNone(winstate.normalize(st, ONE))
        self.assertIsNotNone(winstate.normalize(st, TWO))
        self.assertIsNone(winstate.normalize({"x": -5000, "y": 0, "w": 1300, "h": 800}, TWO))

    def test_rejects_nonsense(self):
        for bad in (None, {}, {"x": 1, "y": 1, "w": 100, "h": 100}, {"x": "a", "y": 1, "w": 1300, "h": 800},
                    {"x": 0, "y": 0, "w": 99999, "h": 800}):
            self.assertIsNone(winstate.normalize(bad, ONE), bad)

    def test_maximized_flag_survives(self):
        st = {"x": 0, "y": 0, "w": 1920, "h": 1040, "maximized": True}
        self.assertTrue(winstate.normalize(st, ONE)["maximized"])

    def test_save_on_close_stores_given_state(self):
        winstate.save_on_close({"x": 10, "y": 10, "w": 1200, "h": 800, "maximized": False})
        self.assertEqual(winstate.load()["w"], 1200)
        winstate.save_on_close({"x": 0, "y": 0, "w": 10, "h": 10, "maximized": False})      # too small: ignored
        self.assertEqual(winstate.load()["w"], 1200)


class FullscreenTests(unittest.TestCase):
    def setUp(self):
        self.win = mock.Mock()
        host.main_window, host._webview = self.win, mock.Mock()
        host._fullscreen, host._pre_fullscreen = False, None
        self.c = backend.app.test_client()

    def tearDown(self):
        host.main_window = host._webview = None
        host._fullscreen, host._pre_fullscreen = False, None

    def test_fullscreen_is_never_the_saved_state(self):
        normal = {"x": 40, "y": 30, "w": 1400, "h": 900, "maximized": True}
        with mock.patch.object(winstate, "capture", return_value=normal):
            self.assertTrue(host.toggle_fullscreen())                       # enter: snapshot taken
            with mock.patch.object(winstate, "capture", return_value={"x": 0, "y": 0, "w": 1920, "h": 1080, "maximized": True}):
                self.assertEqual(host.state_to_save(), normal)             # while fullscreen: the snapshot wins
            self.assertFalse(host.toggle_fullscreen())                      # leave
            self.assertEqual(host.state_to_save(), normal)                  # capture() of the real window again
        self.assertEqual(self.win.toggle_fullscreen.call_count, 2)

    def test_endpoint(self):
        with mock.patch.object(winstate, "capture", return_value=None):
            r = self.c.post("/api/window/fullscreen", headers=HDR).get_json()
        self.assertEqual((r["ok"], r["fullscreen"]), (True, True))

    def test_endpoint_without_window(self):
        host.main_window = None
        self.assertFalse(self.c.post("/api/window/fullscreen", headers=HDR).get_json()["ok"])


if __name__ == "__main__":
    unittest.main()
