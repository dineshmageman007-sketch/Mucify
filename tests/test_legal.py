# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 mageman007 and contributors
import re
import unittest
from pathlib import Path

from tests.helpers import backend, paths
import mucify

ROOT = Path(__file__).resolve().parent.parent
DOCS = ["LICENSE", "THIRD_PARTY.md", "DISCLAIMER.md", "PRIVACY.md", "CREDITS.md", "SECURITY.md", "installer/NOTICE.txt"]


class LegalFilesTests(unittest.TestCase):
    def test_all_documents_exist_and_are_not_empty(self):
        for d in DOCS:
            self.assertGreater((ROOT / d).stat().st_size, 300, d)

    def test_license_is_the_full_gpl3_text(self):
        t = (ROOT / "LICENSE").read_text(encoding="utf-8")
        self.assertIn("GNU GENERAL PUBLIC LICENSE", t)
        self.assertIn("Version 3, 29 June 2007", t)
        self.assertIn("END OF TERMS AND CONDITIONS", t)
        self.assertIn("How to Apply These Terms to Your New Programs", t)
        self.assertGreater(len(t), 34000)

    def test_third_party_is_accurate_about_the_copyleft_pieces(self):
        t = (ROOT / "THIRD_PARTY.md").read_text(encoding="utf-8")
        self.assertIn("GPL-2.0-or-later", t)            # Mutagen
        self.assertNotRegex(t, r"LGPL")                  # was wrong in an earlier draft
        self.assertIn("AGPL-3.0", t)
        self.assertIn("github.com/fiso64/sockseek", t)
        self.assertIn("2.6.0", t)
        self.assertIn("complexlogic", t)
        self.assertTrue((ROOT / "tools/sldl/VERSION.txt").exists())

    def test_disclaimer_and_privacy_cover_the_essentials(self):
        d = (ROOT / "DISCLAIMER.md").read_text(encoding="utf-8").lower()
        for needle in ("not** affiliated", "as is", "copyright", "qobuz", "soulseek"):
            self.assertIn(needle, d)
        p = (ROOT / "PRIVACY.md").read_text(encoding="utf-8").lower()
        for needle in ("plain text", "no accounts, no ads, no analytics", "server.slsknet.org", "%appdata%"):
            self.assertIn(needle, p)

    def test_metadata_is_consistent(self):
        self.assertEqual(mucify.__license__, "GPL-3.0-or-later")
        self.assertTrue(mucify.__author__ and mucify.__url__.startswith("https://github.com/"))
        for d in ("CREDITS.md", "README.md", "installer/NOTICE.txt"):
            self.assertIn(mucify.__author__, (ROOT / d).read_text(encoding="utf-8"), d)
        self.assertIn(mucify.__author__, (ROOT / "installer/mucify.iss").read_text(encoding="utf-8"))

    def test_every_source_file_carries_the_license_header(self):
        files = list((ROOT / "mucify").glob("*.py")) + list((ROOT / "tests").glob("*.py")) + [ROOT / "run_mucify.py",
                ROOT / "mucify/static/app.js", ROOT / "mucify/static/style.css"]
        for f in files:
            self.assertIn("SPDX-License-Identifier: GPL-3.0-or-later", f.read_text(encoding="utf-8")[:400], f.name)

    def test_packaging_bundles_the_documents(self):
        spec = (ROOT / "mucify.spec").read_text(encoding="utf-8")
        for d in ("LICENSE", "THIRD_PARTY.md", "DISCLAIMER.md", "PRIVACY.md", "CREDITS.md"):
            self.assertIn(f'"{d}"', spec)
        ps = (ROOT / "build.ps1").read_text(encoding="utf-8")
        self.assertIn("python-packages.txt", ps)
        self.assertIn("InfoBeforeFile=NOTICE.txt", (ROOT / "installer/mucify.iss").read_text(encoding="utf-8"))


class LegalApiTests(unittest.TestCase):
    def setUp(self):
        self.c = backend.app.test_client()

    def test_about(self):
        a = self.c.get("/api/about").get_json()
        self.assertEqual((a["version"], a["license"]), (mucify.__version__, "GPL-3.0-or-later"))
        ids = {d["id"] for d in a["docs"]}
        self.assertTrue({"license", "third_party", "disclaimer", "privacy", "credits", "sldl_license", "rsgain_license"} <= ids)

    def test_every_listed_document_can_be_read(self):
        for d in self.c.get("/api/about").get_json()["docs"]:
            r = self.c.get(f"/api/legal/{d['id']}")
            self.assertEqual(r.status_code, 200, d["id"])
            self.assertGreater(len(r.get_json()["text"]), 200, d["id"])
        self.assertIn("GNU GENERAL PUBLIC LICENSE", self.c.get("/api/legal/license").get_json()["text"])
        self.assertIn("AFFERO", self.c.get("/api/legal/sldl_license").get_json()["text"])

    def test_only_allow_listed_documents_are_served(self):
        for bad in ("config", "..%2Fapp.py", "SECURITY", "../../etc/passwd", "app"):
            self.assertEqual(self.c.get(f"/api/legal/{bad}").status_code, 404, bad)


if __name__ == "__main__":
    unittest.main()
