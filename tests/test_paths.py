# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 mageman007 and contributors
import os
import unittest
from pathlib import Path
from unittest import mock

from tests.helpers import paths


class PathsTests(unittest.TestCase):
    def test_default_folder_names(self):
        self.assertEqual(paths.default_music_dir().name, "Mucify")
        self.assertEqual(paths.default_music_dir().parent.name, "Music")
        self.assertEqual(paths.default_working_dir().parent, paths.user_data_dir())

    def test_ensure_default_folders(self):
        m, w = paths.ensure_default_folders()
        self.assertTrue(m.is_dir() and w.is_dir())

    def test_sldl_staging_copies_once_and_is_never_downloaded(self):
        import tempfile
        tmp = Path(tempfile.mkdtemp())
        src = tmp / "bundle" / "tools" / "sldl"; src.mkdir(parents=True)
        (src / "sldl.exe").write_bytes(b"MZ-fake-v1")
        with mock.patch.object(paths, "bundle_root", return_value=tmp / "bundle"):
            staged = paths.stage_sldl()
            self.assertEqual(staged.read_bytes(), b"MZ-fake-v1")
            self.assertNotEqual(staged.parent, src)                # runs from the writable AppData copy
            (staged.parent / "sldl.conf").write_text("username = x")   # conf written next to exe survives re-stage
            self.assertEqual(paths.stage_sldl(), staged)
            self.assertTrue((staged.parent / "sldl.conf").exists())

    def test_manual_override_wins_only_if_it_exists(self):
        self.assertTrue(paths.resolve_tool(__file__, "rsgain.exe").endswith("test_paths.py"))
        self.assertTrue(paths.resolve_tool("Z:/nope.exe", "rsgain.exe").endswith("rsgain.exe"))

    def test_repo_ships_the_tested_tools_and_no_credentials(self):
        root = paths.bundle_root()
        self.assertTrue((root / "tools" / "sldl" / "sldl.exe").exists())
        self.assertTrue((root / "tools" / "rsgain" / "rsgain.exe").exists())
        self.assertFalse((root / "tools" / "sldl" / "sldl.conf").exists())


if __name__ == "__main__":
    unittest.main()
