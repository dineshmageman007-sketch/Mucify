# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 mageman007 and contributors
"""
Tiny, dependency-free reader for the title, artist and cover picture of the background music.

Supports MP3 (ID3v2.2 / 2.3 / 2.4, plus ID3v1 as a fallback) and FLAC (Vorbis comments + PICTURE blocks).
Anything unexpected simply returns "no information": a broken tag must never stop the music.
"""
import os
import struct

MAX_TAG = 24 * 1024 * 1024          # never read more than this from one file for tags / pictures


def _sniff_image(data: bytes):
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[:2] == b"BM":
        return "image/bmp"
    return None


def _synchsafe(b: bytes) -> int:
    n = 0
    for x in b:
        n = (n << 7) | (x & 0x7F)
    return n


def _unsync(data: bytes) -> bytes:
    return data.replace(b"\xff\x00", b"\xff")


def _decode(data: bytes, enc: int) -> str:
    try:
        if enc == 0:
            return data.decode("latin-1")
        if enc == 1:
            return data.decode("utf-16")                 # BOM tells the byte order
        if enc == 2:
            return data.decode("utf-16-be")
        return data.decode("utf-8")
    except (UnicodeDecodeError, ValueError):
        return data.decode("latin-1", "replace")


def _split_nul(data: bytes, enc: int):
    """Split off a null-terminated string (2-byte terminator for UTF-16)."""
    if enc in (1, 2):
        i = 0
        while i + 1 < len(data):
            if data[i] == 0 and data[i + 1] == 0:
                return data[:i], data[i + 2:]
            i += 2
        return data, b""
    i = data.find(b"\x00")
    return (data, b"") if i < 0 else (data[:i], data[i + 1:])


def _text_value(payload: bytes) -> str:
    if not payload:
        return ""
    enc, body = payload[0], payload[1:]
    first = _split_nul(body, enc)[0] if enc in (1, 2) else body.split(b"\x00")[0]
    return _decode(first, enc).strip("\x00 \ufeff").strip()


# ----------------------------------------------------------------------------- ID3
def _id3_frames(f):
    """Yield (frame_id, payload) of an ID3v2 tag at the start of the open file."""
    head = f.read(10)
    if len(head) < 10 or head[:3] != b"ID3":
        return
    ver, flags = head[3], head[5]
    size = _synchsafe(head[6:10])
    if ver not in (2, 3, 4) or size > MAX_TAG:
        return
    data = f.read(size)
    if flags & 0x80:
        data = _unsync(data)
    pos = 0
    if flags & 0x40 and ver in (3, 4):                        # skip the extended header
        if len(data) < 4:
            return
        ext = _synchsafe(data[:4]) if ver == 4 else struct.unpack(">I", data[:4])[0] + 4
        pos = ext
    while True:
        if ver == 2:
            if pos + 6 > len(data):
                return
            fid = data[pos:pos + 3]
            n = int.from_bytes(data[pos + 3:pos + 6], "big")
            body_at, fflags = pos + 6, (0, 0)
        else:
            if pos + 10 > len(data):
                return
            fid = data[pos:pos + 4]
            n = _synchsafe(data[pos + 4:pos + 8]) if ver == 4 else struct.unpack(">I", data[pos + 4:pos + 8])[0]
            body_at, fflags = pos + 10, (data[pos + 8], data[pos + 9])
        if fid[:1] == b"\x00" or not fid.strip():
            return
        if n < 0 or body_at + n > len(data):
            return
        payload = data[body_at:body_at + n]
        pos = body_at + n
        try:
            fid_s = fid.decode("ascii")
        except UnicodeDecodeError:
            continue
        if ver == 3:
            if fflags[1] & 0xC0:                              # compressed or encrypted: skip
                continue
            if fflags[1] & 0x20:                              # grouping byte
                payload = payload[1:]
        elif ver == 4:
            if fflags[1] & 0x0C:                              # compressed / encrypted: skip
                continue
            if fflags[1] & 0x40:
                payload = payload[1:]
            if fflags[1] & 0x01:                              # data length indicator
                payload = payload[4:]
            if fflags[1] & 0x02:
                payload = _unsync(payload)
        yield fid_s, payload


def _apic(fid, payload):
    """-> (picture_type, image_bytes) or None."""
    if not payload:
        return None
    enc = payload[0]
    rest = payload[1:]
    if fid == "PIC":                                          # ID3v2.2: 3-letter format
        rest = rest[3:]
    else:
        _mime, rest = _split_nul(rest, 0)
    if not rest:
        return None
    ptype, rest = rest[0], rest[1:]
    _desc, img = _split_nul(rest, enc)
    return ptype, img


def _read_id3(path, want_art):
    info, pictures = {}, []
    names = {"TIT2": "title", "TT2": "title", "TPE1": "artist", "TP1": "artist", "TALB": "album", "TAL": "album"}
    with open(path, "rb") as f:
        for fid, payload in _id3_frames(f):
            if fid in names and names[fid] not in info:
                v = _text_value(payload)
                if v:
                    info[names[fid]] = v
            elif fid in ("APIC", "PIC"):
                p = _apic(fid, payload)
                if p and p[1]:
                    pictures.append(p)
        if not info:                                          # ID3v1 fallback (last 128 bytes)
            try:
                f.seek(-128, os.SEEK_END)
                tail = f.read(128)
                if tail[:3] == b"TAG":
                    t = tail[3:33].split(b"\x00")[0].decode("latin-1").strip()
                    a = tail[33:63].split(b"\x00")[0].decode("latin-1").strip()
                    if t:
                        info["title"] = t
                    if a:
                        info["artist"] = a
            except OSError:
                pass
    cover = None
    if pictures:
        front = [p for p in pictures if p[0] == 3] or pictures
        cover = front[0][1]
    return info, cover


# ----------------------------------------------------------------------------- FLAC
def _read_flac(path, want_art):
    info, pictures = {}, []
    with open(path, "rb") as f:
        if f.read(4) != b"fLaC":
            return info, None
        while True:
            h = f.read(4)
            if len(h) < 4:
                break
            last, btype = bool(h[0] & 0x80), h[0] & 0x7F
            n = int.from_bytes(h[1:4], "big")
            if btype in (4, 6) and n <= MAX_TAG:
                body = f.read(n)
                if btype == 4:
                    _vorbis(body, info)
                elif want_art:
                    p = _flac_picture(body)
                    if p:
                        pictures.append(p)
            else:
                f.seek(n, os.SEEK_CUR)
            if last:
                break
    cover = None
    if pictures:
        front = [p for p in pictures if p[0] == 3] or pictures
        cover = front[0][1]
    return info, cover


def _vorbis(body, info):
    try:
        vlen = struct.unpack("<I", body[:4])[0]
        pos = 4 + vlen
        count = struct.unpack("<I", body[pos:pos + 4])[0]
        pos += 4
        for _ in range(count):
            n = struct.unpack("<I", body[pos:pos + 4])[0]
            entry = body[pos + 4:pos + 4 + n].decode("utf-8", "replace")
            pos += 4 + n
            if "=" in entry:
                k, v = entry.split("=", 1)
                k = k.lower()
                if k in ("title", "artist", "album") and v.strip() and k not in info:
                    info[k] = v.strip()
    except (struct.error, IndexError):
        pass


def _flac_picture(body):
    try:
        ptype = struct.unpack(">I", body[:4])[0]
        pos = 4
        mlen = struct.unpack(">I", body[pos:pos + 4])[0]; pos += 4 + mlen
        dlen = struct.unpack(">I", body[pos:pos + 4])[0]; pos += 4 + dlen
        pos += 16                                             # width, height, depth, colours
        n = struct.unpack(">I", body[pos:pos + 4])[0]; pos += 4
        img = body[pos:pos + n]
        return (ptype, img) if img else None
    except (struct.error, IndexError):
        return None


# ----------------------------------------------------------------------------- public
def _read(path, want_art):
    ext = os.path.splitext(path)[1].lower()
    try:
        if ext == ".flac":
            return _read_flac(path, want_art)
        if ext == ".mp3":
            return _read_id3(path, want_art)
    except (OSError, ValueError, struct.error):
        pass
    return {}, None


def read_info(path) -> dict:
    """{'title', 'artist', 'album', 'has_art'}; the title falls back to the file name."""
    info, cover = _read(path, True)
    mime = _sniff_image(cover) if cover else None
    return {"title": info.get("title") or os.path.splitext(os.path.basename(path))[0],
            "artist": info.get("artist", ""), "album": info.get("album", ""), "has_art": bool(mime)}


def read_cover(path):
    """-> (mime, bytes) or None."""
    _info, cover = _read(path, True)
    mime = _sniff_image(cover) if cover else None
    return (mime, cover) if mime else None
