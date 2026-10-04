# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 mageman007 and contributors
import struct
import tempfile
import unittest
from pathlib import Path

from tests.helpers import HDR, backend
from mucify import audiometa

JPEG = b"\xff\xd8\xff\xe0" + b"JPEGDATA" * 20
PNG = b"\x89PNG\r\n\x1a\n" + b"PNGDATA" * 20


def syncsafe(n):
    return bytes([(n >> 21) & 0x7F, (n >> 14) & 0x7F, (n >> 7) & 0x7F, n & 0x7F])


def frame(fid, payload, ver=3):
    size = syncsafe(len(payload)) if ver == 4 else struct.pack(">I", len(payload))
    return fid.encode() + size + b"\x00\x00" + payload


def id3(frames, ver=3):
    body = b"".join(frames)
    return b"ID3" + bytes([ver, 0, 0]) + syncsafe(len(body)) + body + b"\x00" * 16 + b"\xff\xfb\x90\x00" * 50


def apic(img, ptype=3, enc=0, desc=b""):
    term = b"\x00\x00" if enc in (1, 2) else b"\x00"
    return bytes([enc]) + b"image/jpeg\x00" + bytes([ptype]) + desc + term + img


def flac(title=None, artist=None, pics=()):
    out = b"fLaC" + bytes([0, 0, 0, 34]) + b"\x00" * 34             # STREAMINFO (not last)
    blocks = []
    if title or artist:
        vendor = b"test"
        entries = []
        if title: entries.append(b"TITLE=" + title.encode())
        if artist: entries.append(b"artist=" + artist.encode())
        body = struct.pack("<I", len(vendor)) + vendor + struct.pack("<I", len(entries))
        for e in entries:
            body += struct.pack("<I", len(e)) + e
        blocks.append((4, body))
    for ptype, img in pics:
        mime = b"image/png"
        body = struct.pack(">I", ptype) + struct.pack(">I", len(mime)) + mime + struct.pack(">I", 0) + struct.pack(">IIII", 1, 1, 24, 0) \
               + struct.pack(">I", len(img)) + img
        blocks.append((6, body))
    for i, (t, body) in enumerate(blocks):
        last = 0x80 if i == len(blocks) - 1 else 0
        out += bytes([last | t]) + len(body).to_bytes(3, "big") + body
    return out + b"\xff\xf8" * 100


class ParserTests(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())

    def w(self, name, data):
        p = self.d / name
        p.write_bytes(data)
        return str(p)

    def test_id3v23_latin1_and_cover(self):
        p = self.w("a.mp3", id3([frame("TIT2", b"\x00Midnight City"), frame("TPE1", b"\x00M83"), frame("APIC", apic(JPEG))]))
        i = audiometa.read_info(p)
        self.assertEqual((i["title"], i["artist"], i["has_art"]), ("Midnight City", "M83", True))
        self.assertEqual(audiometa.read_cover(p), ("image/jpeg", JPEG))

    def test_id3v24_utf8_and_front_cover_preferred(self):
        other = apic(PNG, ptype=0)
        front = apic(JPEG, ptype=3, desc=b"front")
        p = self.w("b.mp3", id3([frame("TIT2", b"\x03Caf\xc3\xa9 del Mar", 4), frame("TPE1", b"\x03Ener\xc3\xa9", 4),
                                 frame("APIC", other, 4), frame("APIC", front, 4)], ver=4))
        i = audiometa.read_info(p)
        self.assertEqual((i["title"], i["artist"]), ("Café del Mar", "Eneré"))
        self.assertEqual(audiometa.read_cover(p)[0], "image/jpeg")

    def test_utf16_text_and_description(self):
        title = b"\x01" + "Tadow".encode("utf-16")
        p = self.w("c.mp3", id3([frame("TIT2", title), frame("APIC", apic(PNG, enc=1, desc="cover".encode("utf-16-le")))]))
        self.assertEqual(audiometa.read_info(p)["title"], "Tadow")
        self.assertEqual(audiometa.read_cover(p)[0], "image/png")

    def test_id3v22(self):
        def f2(fid, payload):
            return fid.encode() + len(payload).to_bytes(3, "big") + payload
        pic = b"\x00" + b"JPG" + b"\x03" + b"\x00" + JPEG
        body = b"".join([f2("TT2", b"\x00Old Song"), f2("TP1", b"\x00Old Band"), f2("PIC", pic)])
        data = b"ID3" + bytes([2, 0, 0]) + syncsafe(len(body)) + body + b"\xff\xfb" * 50
        p = self.w("d.mp3", data)
        i = audiometa.read_info(p)
        self.assertEqual((i["title"], i["artist"], i["has_art"]), ("Old Song", "Old Band", True))

    def test_id3v1_fallback_and_filename_fallback(self):
        v1 = b"TAG" + b"Retro Tune".ljust(30, b"\x00") + b"Retro Band".ljust(30, b"\x00") + b"\x00" * 65
        p = self.w("e.mp3", b"\xff\xfb\x90\x00" * 300 + v1)
        i = audiometa.read_info(p)
        self.assertEqual((i["title"], i["artist"], i["has_art"]), ("Retro Tune", "Retro Band", False))
        bare = self.w("My Song.mp3", b"\xff\xfb\x90\x00" * 300)
        self.assertEqual(audiometa.read_info(bare)["title"], "My Song")

    def test_flac(self):
        p = self.w("f.flac", flac("Door", "C418", [(0, JPEG), (3, PNG)]))
        i = audiometa.read_info(p)
        self.assertEqual((i["title"], i["artist"], i["has_art"]), ("Door", "C418", True))
        self.assertEqual(audiometa.read_cover(p), ("image/png", PNG))                 # type 3 (front) wins
        self.assertFalse(audiometa.read_info(self.w("g.flac", flac()))["has_art"])

    def test_garbage_never_raises(self):
        for name, data in (("x.mp3", b"ID3\x03\x00\x00\x7f\x7f\x7f\x7f" + b"\x00" * 50), ("y.flac", b"fLaC\x80\xff\xff\xff"),
                           ("z.mp3", b""), ("w.flac", b"not flac at all")):
            i = audiometa.read_info(self.w(name, data))
            self.assertFalse(i["has_art"])
            self.assertIsNone(audiometa.read_cover(self.w(name, data)))


class MiniPlayerApiTests(unittest.TestCase):
    def setUp(self):
        self.c = backend.app.test_client()
        self.d = Path(tempfile.mkdtemp()) / "Mix"
        self.d.mkdir()
        (self.d / "01 a.mp3").write_bytes(id3([frame("TIT2", b"\x00First"), frame("TPE1", b"\x00Band A"), frame("APIC", apic(JPEG))]))
        (self.d / "02 b.flac").write_bytes(flac("Second", "Band B"))
        self.c.post("/api/bgmusic/set", json={"path": str(self.d)}, headers=HDR)

    def tearDown(self):
        self.c.post("/api/bgmusic/clear", headers=HDR)

    def test_meta_and_art_per_track(self):
        m0 = self.c.get("/api/bgmusic/meta/0").get_json()
        self.assertEqual((m0["title"], m0["artist"], m0["has_art"]), ("First", "Band A", True))
        art = self.c.get("/api/bgmusic/art/0")
        self.assertEqual((art.status_code, art.mimetype, art.data), (200, "image/jpeg", JPEG))
        m1 = self.c.get("/api/bgmusic/meta/1").get_json()
        self.assertEqual((m1["title"], m1["has_art"]), ("Second", False))
        self.assertEqual(self.c.get("/api/bgmusic/art/1").status_code, 404)       # the page falls back to the Mucify logo

    def test_bad_index_and_file_mode(self):
        self.assertEqual(self.c.get("/api/bgmusic/meta/9").status_code, 404)
        self.assertEqual(self.c.get("/api/bgmusic/meta").status_code, 404)       # folder mode needs an index
        single = self.d / "01 a.mp3"
        self.c.post("/api/bgmusic/set", json={"path": str(single)}, headers=HDR)
        self.assertEqual(self.c.get("/api/bgmusic/meta").get_json()["title"], "First")
        self.assertEqual(self.c.get("/api/bgmusic/art").status_code, 200)


if __name__ == "__main__":
    unittest.main()
