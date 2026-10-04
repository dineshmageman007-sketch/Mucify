# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 mageman007 and contributors
import csv
import os
import unittest
from pathlib import Path
from unittest import mock

from tests.helpers import HDR, backend, paths
from mucify import projects


def write_csv(path, fieldnames, rows):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)


def same_path(a, b):
    """Windows can name one folder two ways (C:\\Users\\RUNNER~1 vs C:\\Users\\runneradmin): compare the real location."""
    return os.path.normcase(os.path.realpath(str(a))) == os.path.normcase(os.path.realpath(str(b)))


def read_csv(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


class ProjectHelperTests(unittest.TestCase):
    def test_names(self):
        self.assertEqual(projects.slug('My: "Mix"/2026?'), "My Mix 2026")
        self.assertEqual(projects.slug("CON"), "Playlist")
        self.assertEqual(projects.playlist_name_from_path("C:/x/20261002_094800_Road Trip.csv"), "Road Trip")
        self.assertTrue(projects.playlist_name_from_path("to_download_20261002_094800.csv").startswith("Playlist "))

    def test_folder_for_input(self):
        wd = paths.user_data_dir() / "WD"
        (wd / "Road Trip").mkdir(parents=True, exist_ok=True)
        inside = wd / "Road Trip" / "2_enriched.csv"
        inside.write_text("x")
        self.assertEqual(projects.folder_for_input(wd, inside), (wd / "Road Trip").resolve())
        self.assertEqual(projects.folder_for_input(wd, "C:/elsewhere/Gym Mix.csv"), wd / "Gym Mix")

    def test_recent_store_drops_missing_files(self):
        store = paths.user_data_dir() / "r.json"
        f = paths.user_data_dir() / "exists.csv"; f.write_text("a")
        projects.remember(store, "enriched", f, "P", 3)
        projects.remember(store, "to_download", paths.user_data_dir() / "gone.csv", "P", 1)
        r = projects.recent(store)
        self.assertIn("enriched", r)
        self.assertNotIn("to_download", r)


class PlaylistFolderFlowTests(unittest.TestCase):
    def setUp(self):
        if backend.CONFIG_PATH.exists():
            backend.CONFIG_PATH.unlink()
        backend.save_library({})
        self.c = backend.app.test_client()
        self.wd = Path(self.c.get("/api/settings").get_json()["paths"]["working_dir"])

    def test_compare_saves_1_to_download_in_playlist_folder_and_remembers_it(self):
        backend.save_library({"T1": {"Spotify Track Id": "T1", "Track Name": "Have", "Artist Name(s)": "A"}})
        src = paths.uploads_dir() / "20261002_101010_My Mix.csv"
        write_csv(src, ["Spotify Track Id", "Track Name", "Artist Name(s)"],
                  [{"Spotify Track Id": "T1", "Track Name": "Have", "Artist Name(s)": "A"},
                   {"Spotify Track Id": "T2", "Track Name": "New", "Artist Name(s)": "B"}])
        r = self.c.post("/api/playlist/compare", json={"path": str(src)}, headers=HDR).get_json()
        self.assertEqual((r["already_have_count"], r["to_download_count"]), (1, 1))
        saved = self.wd / "My Mix" / "1_to_download.csv"
        self.assertTrue(saved.exists())
        self.assertEqual([x["Track Name"] for x in read_csv(saved)], ["New"])
        rec = self.c.get("/api/recent").get_json()
        self.assertTrue(same_path(rec["to_download"]["path"], saved))
        self.assertTrue(same_path(rec["source"]["path"], src))

    def test_nothing_new_creates_no_folder(self):
        backend.save_library({"T1": {"Spotify Track Id": "T1", "Track Name": "Have"}})
        src = paths.uploads_dir() / "20261002_101011_All Owned.csv"
        write_csv(src, ["Spotify Track Id", "Track Name"], [{"Spotify Track Id": "T1", "Track Name": "Have"}])
        r = self.c.post("/api/playlist/compare", json={"path": str(src)}, headers=HDR).get_json()
        self.assertEqual(r["to_download_count"], 0)
        self.assertFalse((self.wd / "All Owned").exists())

    def test_enrich_writes_2_enriched_in_playlist_folder(self):
        folder = self.wd / "Gym"
        src = folder / "1_to_download.csv"
        write_csv(src, ["Song", "Artist", "Album", "Time"], [{"Song": "One", "Artist": "A", "Album": "X", "Time": "3:00"}])
        out = projects.folder_for_input(self.wd, src)
        backend.qobuz_enrich_thread(str(src), str(out), 48000, 24, "2_enriched.csv")
        self.assertTrue((folder / "2_enriched.csv").exists())
        self.assertTrue(same_path(self.c.get("/api/recent").get_json()["enriched"]["path"], folder / "2_enriched.csv"))


class DownloaderResultsTests(unittest.TestCase):
    """Runs the real downloader loop with the Soulseek bits replaced by fakes."""

    FIELDS = ["album", "title", "artist", "duration_ms", "Time", "max_khz", "max_bit", "quality_status"]

    def setUp(self):
        if backend.CONFIG_PATH.exists():
            backend.CONFIG_PATH.unlink()
        self.c = backend.app.test_client()
        self.wd = Path(self.c.get("/api/settings").get_json()["paths"]["working_dir"])
        self.folder = self.wd / "Mix"
        for f in self.folder.glob("*") if self.folder.exists() else []:
            f.unlink()

    def _row(self, title):
        return {"album": "Al", "title": title, "artist": "Ar", "duration_ms": "200000", "Time": "3:20",
                "max_khz": "44100", "max_bit": "16", "quality_status": "found"}

    def _run(self, csv_path, outcome):
        calls = {"download": {}, "pick_floor": []}

        def fake_pick(results, target_sec, max_khz, max_bit, title, banned=None, min_khz=None, min_bit=None):
            banned = banned or set()
            if outcome[title] == "nomatch":
                return None
            n = len(banned)
            if n >= 40:
                return None
            calls["pick_floor"].append((title, min_khz, min_bit))
            return {"username": f"peer{n}", "khz": 44100, "bit": 16, "size": 30_000_000, "speed": 500, "input": "x"}

        def fake_dl(exe, vault, user, inp, *a):
            calls["download"][user] = calls["download"].get(user, 0) + 1
            calls["download"]["_total"] = calls["download"].get("_total", 0) + 1
            return "success" if outcome[self._current] == "ok" else "failed"

        # remember which title is being downloaded (fake_pick sees it first for every attempt)
        orig_pick = fake_pick

        def tracking_pick(*a, **k):
            self._current = a[4]
            return orig_pick(*a, **k)

        with mock.patch.object(backend, "run_search", return_value=[1]), \
             mock.patch.object(backend, "pick_best", tracking_pick), \
             mock.patch.object(backend, "download_with_monitor", fake_dl):
            backend.downloader_engine_thread(str(csv_path))
        return calls

    def test_results_split_into_skipped_and_successful_and_retry_limit_is_15(self):
        self.assertEqual(backend.MAX_ATTEMPTS, 15)
        src = self.folder / "2_enriched.csv"
        rows = [self._row("Good"), self._row("Nope"), self._row("Stubborn"), {**self._row(""), "title": ""}, self._row("Never")]
        write_csv(src, self.FIELDS, rows)
        outcome = {"Good": "ok", "Nope": "nomatch", "Stubborn": "fail", "Never": "ok"}
        # stop the run before the last track
        original = backend.downloader_job.stop_flag

        class StopAfter:
            def __init__(self): self.n = 0
            def is_set(self_inner):
                self_inner.n += 1
                return self_inner.n > 4          # rows 1-4 are processed, row 5 is not attempted
            def clear(self_inner): pass
            def set(self_inner): pass

        backend.downloader_job.stop_flag = StopAfter()
        try:
            calls = self._run(src, outcome)
        finally:
            backend.downloader_job.stop_flag = original
        self.assertEqual(calls["download"]["_total"], 1 + 15)          # Good once, Stubborn exactly 15 times
        # the quality floor chosen on the first pick is passed on to every later attempt
        stubborn = [f for t, *f in calls["pick_floor"] if t == "Stubborn"]
        # 1 search probe + attempt 1 have no floor yet; attempts 2..15 must all carry the first pick's quality
        self.assertEqual(len(stubborn), 2 + 14)
        self.assertEqual(stubborn[:2], [[None, None], [None, None]])
        self.assertTrue(all(f == [44100, 16] for f in stubborn[2:]))

        ok = read_csv(self.folder / "4_successful.csv")
        sk = read_csv(self.folder / "3_skipped.csv")
        self.assertEqual([r["title"] for r in ok], ["Good"])
        self.assertEqual(sorted(r["result"] for r in sk),
                         ["all_downloads_failed", "no_result", "not_attempted", "skipped_missing_fields"])
        self.assertEqual({r["title"] for r in sk if r["result"] == "not_attempted"}, {"Never"})
        self.assertEqual(self.c.get("/api/recent").get_json()["downloaded"]["name"], "Mix")

    def test_rerunning_the_skipped_list_keeps_earlier_successes(self):
        src = self.folder / "2_enriched.csv"
        write_csv(src, self.FIELDS, [self._row("A"), self._row("B")])
        self._run(src, {"A": "ok", "B": "nomatch"})
        self.assertEqual([r["title"] for r in read_csv(self.folder / "4_successful.csv")], ["A"])
        self._run(self.folder / "3_skipped.csv", {"B": "ok"})
        self.assertEqual(sorted(r["title"] for r in read_csv(self.folder / "4_successful.csv")), ["A", "B"])
        self.assertFalse((self.folder / "3_skipped.csv").exists())      # nothing left undownloaded

    def test_fresh_run_removes_stale_lists(self):
        src = self.folder / "2_enriched.csv"
        write_csv(src, self.FIELDS, [self._row("A")])
        self._run(src, {"A": "nomatch"})
        self.assertTrue((self.folder / "3_skipped.csv").exists())
        self.assertFalse((self.folder / "4_successful.csv").exists())
        self._run(src, {"A": "ok"})
        self.assertFalse((self.folder / "3_skipped.csv").exists())
        self.assertTrue((self.folder / "4_successful.csv").exists())


class LibraryBackupTests(unittest.TestCase):
    def setUp(self):
        self.c = backend.app.test_client()
        backend.save_library({})

    def test_empty_library(self):
        self.assertEqual(self.c.post("/api/playlist/backup", headers=HDR).status_code, 400)

    def test_backup_roundtrip(self):
        backend.save_library({
            "T1": {"Spotify Track Id": "T1", "Track Name": "One", "_source_file": "a.csv"},
            "T2": {"Spotify Track Id": "T2", "Track Name": "Two", "Album": "X", "_source_file": "b.csv"},
        })
        dest = paths.user_data_dir() / "backup.csv"
        with mock.patch.object(backend.host, "save_dialog", return_value=str(dest)):
            r = self.c.post("/api/playlist/backup", headers=HDR).get_json()
        self.assertEqual((r["ok"], r["count"]), (True, 2))
        rows = read_csv(dest)
        self.assertEqual({x["Track Name"] for x in rows}, {"One", "Two"})
        self.assertIn("Album", rows[0])
        # the backup can be fed straight back into an empty library
        backend.save_library({})
        out = self.c.post("/api/playlist/upload", json={"paths": [str(dest)]}, headers=HDR).get_json()
        self.assertEqual(out["library_size"], 2)

    def test_cancelled_dialog(self):
        backend.save_library({"T1": {"Spotify Track Id": "T1"}})
        with mock.patch.object(backend.host, "save_dialog", return_value=None):
            r = self.c.post("/api/playlist/backup", headers=HDR).get_json()
        self.assertTrue(r["cancelled"])


if __name__ == "__main__":
    unittest.main()
