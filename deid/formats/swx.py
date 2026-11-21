"""SolidWorks 2015+ container (non-OLE .sldprt/.sldasm/.slddrw).

The file is a sequence of records:

    14 00 06 00 08 00 | 4 bytes | u32 crc32(uncompressed) | u32 csize | u32 usize | u32 namelen
    | name (each byte nibble-swapped) | raw-deflate data (csize bytes)

Sections hold docProps/*.xml (creator, last modified by, custom properties, vault paths),
Contents/* binary streams, previews, ... We rewrite section payloads with same-length
replacements, recompute the CRC and recompress. The new deflate stream is padded with
zeros up to the original csize, so every record keeps its offset and size field and the
file length never changes (raw inflate stops at the end of the stream). A section whose
recompressed stream would be larger is left untouched.
"""

from __future__ import annotations

import re
import struct
import zlib

MARK = b"\x14\x00\x06\x00\x08\x00"
SKIP_SECTIONS = ("Preview", "PreviewPNG", "Contents/DisplayLists", "Contents/Config-0-LWDATA")


def _swap(b: bytes) -> bytes:
    return bytes(((c << 4) | (c >> 4)) & 0xFF for c in b)


def is_swx(data: bytes) -> bool:
    return not data.startswith(b"\xd0\xcf\x11\xe0") and MARK in data[:4096]


def records(data: bytes):
    """Valid records: (header offset, name, data start, csize, usize, payload)."""
    out = []
    pos = 0
    while True:
        h = data.find(MARK, pos)
        if h < 0:
            break
        pos = h + 1
        if h + 26 > len(data):
            break
        crc, cs, us, nl = struct.unpack_from("<IIII", data, h + 10)
        if not (0 < nl < 512 and 0 < cs <= len(data) - h - 26 - nl and us < 512 * 1024 * 1024):
            continue
        st = h + 26 + nl
        try:
            payload = zlib.decompressobj(-15).decompress(data[st:st + cs])
        except zlib.error:
            continue
        if len(payload) != us or (zlib.crc32(payload) & 0xFFFFFFFF) != crc:
            continue
        name = _swap(data[h + 26:st]).decode("latin-1")
        out.append((h, name, st, cs, us, payload))
        pos = st + cs
    return out


def _deflate(b: bytes) -> bytes:
    best = None
    for level in (9, 6):
        c = zlib.compressobj(level, zlib.DEFLATED, -15, 9)
        s = c.compress(b) + c.flush()
        if best is None or len(s) < len(best):
            best = s
    return best


def rewrite(data: bytes, transform) -> bytes:
    """transform(section_name, payload) -> same-length payload."""
    recs = records(data)
    if not recs:
        return data
    buf = None
    for h, name, st, cs, us, payload in recs:
        if name.startswith(SKIP_SECTIONS):
            continue
        new = transform(name, payload)
        if new == payload or len(new) != len(payload):
            continue
        comp = _deflate(new)
        if len(comp) > cs:
            continue
        if buf is None:
            buf = bytearray(data)
        buf[st:st + cs] = comp + b"\x00" * (cs - len(comp))
        struct.pack_into("<I", buf, h + 10, zlib.crc32(new) & 0xFFFFFFFF)
    if buf is None:
        return data
    out = bytes(buf)
    # self-check: same length, same record table, every section inflates and matches its CRC
    chk = records(out)
    if len(out) != len(data) or [(r[0], r[1], r[3], r[4]) for r in chk] != [(r[0], r[1], r[3], r[4]) for r in recs]:
        raise ValueError("swx record table changed")
    return out


CORE_RX = re.compile(rb"<(dc:creator|cp:lastModifiedBy|cp:lastPrinted|dc:title|cp:keywords)>([^<]{1,120})</")
PROP_RX = re.compile(rb'<property[^>]*name="([^"]{1,60})"[^>]*>\s*<vt:lpwstr>([^<]{1,200})</vt:lpwstr>|'
                     rb'<property[^>]*name="([^"]{1,60})"[^>]*>\s*<vt:lpstr>([^<]{1,200})</vt:lpstr>')
PEOPLE_PROP = re.compile(r"(?i)author|drawn|designer|engineer|checked|approved|created ?by|owner|zeichner|"
                         r"gezeichnet|gepr|bearbeiter|dessin|responsable|dibuj|revis")
COMPANY_PROP = re.compile(r"(?i)company|firma|client|customer|vendor|supplier|soci[eé]t[eé]|empresa")


def harvest(data: bytes) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    try:
        recs = records(data)
    except Exception:
        return out
    for h, name, st, cs, us, payload in recs:
        if not name.startswith("docProps/"):
            continue
        for tag, val in CORE_RX.findall(payload):
            v = val.decode("utf-8", "replace").strip()
            if tag == b"dc:creator":
                out.append((v, "person_field"))
            elif tag == b"cp:lastModifiedBy":
                out.append((v, "account_field"))
        for m in PROP_RX.finditer(payload):
            pname = (m.group(1) or m.group(3) or b"").decode("utf-8", "replace")
            val = (m.group(2) or m.group(4) or b"").decode("utf-8", "replace").strip()
            if not val or val.startswith("$PRP") or val.startswith('"SW-'):
                continue
            if PEOPLE_PROP.search(pname) and not re.search(r"\d{3}", val):
                out.append((val, "person_field"))
            elif COMPANY_PROP.search(pname):
                out.append((val, "company_field"))
            elif pname in ("SW-Folder Name",):
                for u in re.findall(r"(?i)\\(?:users|documents and settings)\\([^\\]{2,40})\\", val):
                    out.append((u, "account"))
    return out
