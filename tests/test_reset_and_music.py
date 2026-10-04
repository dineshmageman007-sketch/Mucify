# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 mageman007 and contributors
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.helpers import HDR, backend, paths
from mucify import projects, reset


def make_playlist_folder(parent, name, extra=None):
    d = Path(parent) / name
    d.mkdir(parents=True, exist_ok=True)
    for f in projects.STAGE_FILES.values():
        (d / f).write_text("a,b\n1,2\n")
    if extra:
        (d / extra).write_text("mine")
    return d


class ResetSafetyTests(unittest.TestCase):
    def test_protected_and_unknown_folders_are_refused(self):
        home = Path.home()
        stranger = Path(tempfile.mkdtemp()) / "My Photos"
        stranger.mkdir()
        (stranger / "pic.jpg").write_text("x")
        for p in (home, home / "Documents", Path(Path.cwd().anchor), stranger):
            self.assertFalse(reset.target_allowed(p), p)
        failed = reset.apply_plan({"targets": [str(stranger)]}, wait=False, pause=0)
        self.assertTrue((stranger / "pic.jpg").exists())
        self.assertEqual(len(failed), 1)

    def test_only_stage_only_playlist_folders_are_listed(self):
        wd = Path(tempfile.mkdtemp()) / "Custom Working"
        ok = make_playlist_folder(wd, "Road Trip")
        mixed = make_playlist_folder(wd, "Has My File", extra="notes.txt")
        (wd / "random").mkdir(); (wd / "random" / "x.txt").write_text("x")
        self.assertEqual(reset.playlist_folders(wd), [ok])
        reset.apply_plan({"targets": [str(ok), str(mixed)]}, wait=False, pause=0)
        self.assertFalse(ok.exists())
        self.assertTrue((mixed / "notes.txt").exists())

    def test_app_data_and_default_music_are_wiped_but_other_music_is_not(self):
        base = Path(tempfile.mkdtemp())
        data = base / "Mucify"; (data / "webview").mkdir(parents=True); (data / "config.json").write_text("{}")
        music = base / "Music"
        default_music = music / "Mucify"; default_music.mkdir(parents=True); (default_music / "a.flac").write_text("x")
        other = music / "My Collection"; other.mkdir(); (other / "b.flac").write_text("x")
        with mock.patch.dict(os.environ, {"MUCIFY_HOME": str(data)}), \
             mock.patch.object(paths, "windows_music_dir", return_value=music):
            cfg = {"paths": {"working_dir": str(data / "Working"), "music_vault": str(default_music)}}
            pv = reset.preview(cfg)
            self.assertTrue(pv["music"]["deletable"])
            plan = reset.build_plan(cfg, "reset", delete_playlists=True, delete_music=True)
            self.assertEqual(set(plan["targets"]), {str(data), str(default_music)})
            self.assertEqual(reset.apply_plan(plan, wait=False, pause=0), [])
            self.assertFalse(data.exists() or default_music.exists())
            self.assertTrue((other / "b.flac").exists())
            # a custom music folder is never offered for deletion
            cfg2 = {"paths": {"working_dir": str(data / "Working"), "music_vault": str(other)}}
            self.assertFalse(reset.preview(cfg2)["music"]["deletable"])
            self.assertNotIn(str(other), reset.build_plan(cfg2, "uninstall", True, True)["targets"])

    def test_music_is_kept_unless_asked(self):
        base = Path(tempfile.mkdtemp())
        music = base / "Music" / "Mucify"; music.mkdir(parents=True)
        with mock.patch.dict(os.environ, {"MUCIFY_HOME": str(base / "Mucify")}), \
             mock.patch.object(paths, "windows_music_dir", return_value=base / "Music"):
            cfg = {"paths": {"working_dir": str(base / "Mucify" / "Working"), "music_vault": str(music)}}
            self.assertNotIn(str(music), reset.build_plan(cfg, "reset", True, False)["targets"])


class ResetApiTests(unittest.TestCase):
    def setUp(self):
        self.c = backend.app.test_client()

    def test_preview_shape(self):
        pv = self.c.get("/api/reset/preview").get_json()
        self.assertIn("app_data", pv); self.assertIn("music", pv); self.assertIn("can_uninstall", pv)

    def test_refuses_while_a_job_runs(self):
        with mock.patch.object(backend.downloader_job, "running", True):
            r = self.c.post("/api/reset/run", json={"mode": "reset"}, headers=HDR)
        self.assertEqual(r.status_code, 409)

    def test_run_starts_helper_and_quits(self):
        with mock.patch.object(reset, "spawn_helper", return_value=True) as sp, \
             mock.patch.object(backend.host, "quit_app") as q, \
             mock.patch.object(backend.threading, "Timer") as timer:
            r = self.c.post("/api/reset/run", json={"mode": "uninstall", "delete_music": True}, headers=HDR)
        self.assertEqual(r.status_code, 200)
        plan = sp.call_args[0][0]
        self.assertEqual(plan["mode"], "uninstall")
        self.assertEqual(plan["targets"][0], str(paths.user_data_dir()))
        timer.assert_called_once()

    def test_helper_flag_is_routed_without_a_window(self):
        plan = Path(tempfile.mkdtemp()) / "plan.json"
        victim = make_playlist_folder(Path(tempfile.mkdtemp()), "Gone")
        import json
        plan.write_text(json.dumps({"mode": "x", "targets": [str(victim)], "pid": 0}))
        self.assertEqual(reset.run_helper(str(plan)), 0)
        self.assertFalse(victim.exists())


class BackgroundMusicTests(unittest.TestCase):
    def setUp(self):
        self.c = backend.app.test_client()
        self.c.post("/api/bgmusic/clear", headers=HDR)
        self.dir = Path(tempfile.mkdtemp())

    def _file(self, name, data=b"ID3" + bytes(range(256)) * 40):
        p = self.dir / name
        p.write_bytes(data)
        return p

    def test_accepts_mp3_and_flac_only(self):
        self.assertEqual(self.c.post("/api/bgmusic/set", json={"path": str(self._file("a.wav"))}, headers=HDR).status_code, 400)
        self.assertEqual(self.c.post("/api/bgmusic/set", json={"path": str(self.dir / "missing.mp3")}, headers=HDR).status_code, 404)
        for name, mime in (("song.mp3", "audio/mpeg"), ("song.FLAC", "audio/flac")):
            f = self._file(name)
            self.assertEqual(self.c.post("/api/bgmusic/set", json={"path": str(f)}, headers=HDR).status_code, 200)
            r = self.c.get("/api/bgmusic")
            self.assertEqual((r.status_code, r.mimetype), (200, mime))
            self.assertEqual(r.data, f.read_bytes())

    def test_range_requests_work_for_streaming(self):
        f = self._file("song.mp3")
        self.c.post("/api/bgmusic/set", json={"path": str(f)}, headers=HDR)
        r = self.c.get("/api/bgmusic", headers={"Range": "bytes=0-99"})
        self.assertEqual(r.status_code, 206)
        self.assertEqual(len(r.data), 100)

    def test_toggle_volume_and_clear_persist(self):
        self.c.post("/api/bgmusic/set", json={"path": str(self._file("s.mp3"))}, headers=HDR)
        self.assertTrue(self.c.get("/api/settings").get_json()["app"]["bgm_enabled"])
        self.c.post("/api/settings", json={"app": {"bgm_enabled": False, "bgm_volume": 0.25}}, headers=HDR)
        a = self.c.get("/api/settings").get_json()["app"]
        self.assertEqual((a["bgm_enabled"], a["bgm_volume"]), (False, 0.25))
        self.c.post("/api/bgmusic/clear", headers=HDR)
        self.assertEqual(self.c.get("/api/bgmusic").status_code, 404)
        self.assertEqual(self.c.get("/api/settings").get_json()["app"]["bgm_path"], "")


    # ---- folder (shuffle) mode
    def _music_folder(self):
        d = Path(tempfile.mkdtemp()) / "My Mix"
        (d / "sub").mkdir(parents=True)
        for rel, data in (("b.mp3", b"B" * 500), ("a.flac", b"A" * 500), ("sub/c.MP3", b"C" * 500),
                          ("notes.txt", b"nope"), ("cover.jpg", b"img")):
            (d / rel).write_bytes(data)
        return d

    def test_folder_lists_only_mp3_flac_including_subfolders(self):
        d = self._music_folder()
        r = self.c.post("/api/bgmusic/set", json={"path": str(d)}, headers=HDR).get_json()
        self.assertEqual((r["ok"], r["kind"], r["count"]), (True, "folder", 3))
        t = self.c.get("/api/bgmusic/tracks").get_json()
        self.assertEqual(t["kind"], "folder")
        self.assertEqual([x["name"] for x in t["tracks"]], ["a", "b", "c"])

    def test_folder_tracks_are_served_by_index_only(self):
        d = self._music_folder()
        self.c.post("/api/bgmusic/set", json={"path": str(d)}, headers=HDR)
        self.assertEqual(self.c.get("/api/bgmusic/track/0").data, b"A" * 500)
        self.assertEqual(self.c.get("/api/bgmusic/track/2").mimetype, "audio/mpeg")
        self.assertEqual(self.c.get("/api/bgmusic/track/3").status_code, 404)
        self.assertEqual(self.c.get("/api/bgmusic/track/1", headers={"Range": "bytes=0-9"}).status_code, 206)
        self.assertEqual(self.c.get("/api/bgmusic").status_code, 404)      # single-file route is not used in folder mode

    def test_folder_without_music_is_rejected(self):
        empty = Path(tempfile.mkdtemp()) / "Empty"; empty.mkdir(); (empty / "x.txt").write_text("x")
        r = self.c.post("/api/bgmusic/set", json={"path": str(empty)}, headers=HDR)
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.c.get("/api/settings").get_json()["app"]["bgm_path"], "")

    def test_single_file_still_reports_file_kind(self):
        self.c.post("/api/bgmusic/set", json={"path": str(self._file("one.mp3"))}, headers=HDR)
        self.assertEqual(self.c.get("/api/bgmusic/tracks").get_json()["kind"], "file")

    def test_file_dialog_filter_exists(self):
        self.assertIn("audio", backend.host.FILETYPES)


if __name__ == "__main__":
    unittest.main()
