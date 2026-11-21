"""Geometry-preserving fingerprints (agent B).

A fingerprint keeps everything de-identification must not change (geometry,
dimensions, units, structure) and masks only the text that may legitimately be
pseudonymized. Input and output fingerprints must be equal for a file to count
as "usable". None means "no fingerprint for this format" (callers fall back to
a coarse structure check).
"""

from __future__ import annotations

import hashlib
import io
import re
import struct
import zipfile

_STEP_STR = re.compile(rb"'(?:[^']|'')*'")
_NUM = re.compile(rb"[-+]?(?:\d+\.\d*|\.\d+|\d+)(?:[EeDd][-+]?\d+)?")


def _h(*parts) -> str:
    m = hashlib.sha256()
    for p in parts:
        m.update(p if isinstance(p, bytes) else repr(p).encode())
        m.update(b"\x00")
    return m.hexdigest()[:24]


def step_fp(data: bytes):
    i = data.find(b"DATA;")
    body = data[i:] if i >= 0 else data
    return ("step", _h(_STEP_STR.sub(b"''", body)))


def _mask_hollerith(s: bytes) -> bytes:
    out, i = bytearray(), 0
    while i < len(s):
        m = re.compile(rb"(\d+)H").match(s, i)
        if m and (i == 0 or s[i - 1:i] in b",; "):
            n = int(m.group(1))
            out += b"H"
            i = m.end() + n
        else:
            out += s[i:i + 1]
            i += 1
    return bytes(out)


def iges_fp(data: bytes):
    lines = data.splitlines()
    d = b"".join(l[:72] for l in lines if l[72:73] == b"D")
    p = b"".join(l[:64] for l in lines if l[72:73] == b"P")
    return ("iges", _h(d, _mask_hollerith(p)))


def stl_fp(data: bytes):
    if len(data) >= 84:
        n = struct.unpack("<I", data[80:84])[0]
        if 84 + 50 * n == len(data):
            return ("stl-bin", n, _h(data[84:]))
    geo = [l.strip() for l in data.splitlines() if l.strip().startswith((b"facet", b"vertex", b"endloop", b"endfacet"))]
    return ("stl-ascii", len(geo), _h(b"\n".join(geo)))


def obj_fp(data: bytes):
    keep = [l.strip() for l in data.splitlines() if l[:2] in (b"v ", b"vt", b"vn", b"f ", b"l ", b"vp")]
    return ("obj", len(keep), _h(b"\n".join(keep)))


def dxf_fp(data: bytes):
    lines = data.splitlines()
    pairs = []
    for k in range(0, len(lines) - 1, 2):
        code = lines[k].strip()
        try:
            c = int(code)
        except ValueError:
            return None
        val = lines[k + 1].strip()
        # geometry, sizes, flags, handles and layer structure; free text (1-9, 999, 1000-1009) masked
        if 1 <= c <= 9 or c == 999 or 1000 <= c <= 1009 or c in (300, 301, 302, 303, 304, 305, 306, 307, 308, 309):
            val = b""
        pairs.append((c, val))
    return ("dxf", len(pairs), _h(repr(pairs).encode()))


def pdf_fp(data: bytes):
    import pikepdf

    with pikepdf.open(io.BytesIO(data)) as p:
        boxes = []
        for pg in p.pages:
            try:
                boxes.append(tuple(round(float(x), 2) for x in pg.mediabox))
            except Exception:
                boxes.append(None)
        return ("pdf", len(p.pages), _h(repr(boxes).encode()))


def ole_fp(data: bytes):
    import olefile

    o = olefile.OleFileIO(io.BytesIO(data))
    try:
        sizes = sorted(o.get_size(s) for s in o.listdir(streams=True, storages=False))
        return ("ole", len(sizes), _h(repr(sizes).encode()))
    finally:
        o.close()


def zip_fp(data: bytes, depth: int = 0):
    z = zipfile.ZipFile(io.BytesIO(data))
    members = []
    for info in z.infolist():
        if info.is_dir():
            continue
        ext = info.filename.rsplit(".", 1)[-1].lower() if "." in info.filename.rsplit("/", 1)[-1] else ""
        sub = None
        if depth < 2 and info.file_size < 100_000_000:
            try:
                sub = fingerprint(z.read(info), ext, depth + 1)
            except Exception:
                sub = ("unreadable",)
        members.append((ext, sub))
    return ("zip", len(members), _h(repr(sorted(members, key=repr)).encode()))


def fingerprint(data: bytes, ext: str, depth: int = 0):
    """Format fingerprint; raises on unparsable input."""
    if not data:
        return ("empty",)
    if data.startswith(b"ISO-10303-21"):
        return step_fp(data)
    if data.startswith(b"%PDF"):
        return pdf_fp(data)
    if data.startswith(b"PK\x03\x04"):
        return zip_fp(data, depth)
    if data.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
        return ole_fp(data)
    if ext == "stl":
        return stl_fp(data)
    if ext == "obj":
        return obj_fp(data)
    if ext in ("igs", "iges"):
        return iges_fp(data)
    if ext == "dxf":
        fp = dxf_fp(data)
        if fp:
            return fp
    # same-length pseudonyms keep every other format's size
    return ("bytes", len(data))
