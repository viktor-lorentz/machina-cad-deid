"""Minimal OLE property-set (MS-OLEPS) reader for identity harvesting."""

from __future__ import annotations

import io
import struct
import uuid

SUMMARY = "f29f85e0-4ff9-1068-ab91-08002b27b3d9"
DOCSUMMARY = "d5cdd502-2e9c-101b-9397-08002b2cf9ae"
INV_DESIGN_TRACKING = "32853f0f-3444-11d1-9e93-0060b03c1ca6"

# (fmtid, pid) -> kind
IDENTITY_PIDS = {
    (SUMMARY, 4): "person",      # Author
    (SUMMARY, 8): "account",     # Last saved by
    (DOCSUMMARY, 14): "person",  # Manager
    (DOCSUMMARY, 15): "company",  # Company
}
# Inventor "Design Tracking Properties" (documented PIDs): people and vendor fields only
INV_PEOPLE_PIDS = {10: "person",   # Checked By
                   12: "person",   # Engr Approved By
                   34: "person",   # Mfg Approved By
                   41: "person",   # Designer
                   42: "person",   # Engineer
                   30: "company",  # Vendor
                   }
# Inventor "Design Tracking Control" stream also stores the last user (pid 16)
INV_CONTROL = "d861fb30-6a2b-11d1-9e98-0060b03c1ca6"


def parse(body: bytes, positions: bool = False) -> list:
    """(fmtid, pid, value) for every string property; with positions=True also (offset, nbytes, codec)."""
    out: list = []
    try:
        if len(body) < 48:
            return out
        nsets = struct.unpack_from("<I", body, 24)[0]
        for i in range(min(nsets, 4)):
            fmtid = str(uuid.UUID(bytes_le=body[28 + 20 * i:44 + 20 * i]))
            off = struct.unpack_from("<I", body, 44 + 20 * i)[0]
            size, n = struct.unpack_from("<II", body, off)
            codepage = 1252
            entries = [struct.unpack_from("<II", body, off + 8 + 8 * k) for k in range(min(n, 400))]
            for pid, po in entries:
                if pid == 1:
                    vt = struct.unpack_from("<I", body, off + po)[0] & 0xFFFF
                    if vt == 2:
                        codepage = struct.unpack_from("<H", body, off + po + 4)[0]
            for pid, po in entries:
                p = off + po
                if p + 8 > len(body):
                    continue
                vt = struct.unpack_from("<I", body, p)[0] & 0xFFFF
                if vt == 30:  # VT_LPSTR
                    cnt = struct.unpack_from("<I", body, p + 4)[0]
                    raw = body[p + 8:p + 8 + cnt]
                    enc = "utf-16-le" if codepage == 1200 else f"cp{codepage}" if codepage not in (65001,) else "utf-8"
                    try:
                        s = raw.decode(enc, "replace")
                    except LookupError:
                        enc = "latin-1"
                        s = raw.decode("latin-1")
                    nbytes = cnt
                elif vt == 31:  # VT_LPWSTR
                    cnt = struct.unpack_from("<I", body, p + 4)[0]
                    enc, nbytes = "utf-16-le", 2 * cnt
                    s = body[p + 8:p + 8 + nbytes].decode("utf-16-le", "replace")
                else:
                    continue
                s = s.strip("\x00 ").strip()
                if s:
                    out.append((fmtid, pid, s, (p + 8, nbytes, enc)) if positions else (fmtid, pid, s))
    except (struct.error, ValueError):
        pass
    return out


def _kind(fmtid: str, pid: int) -> str | None:
    kind = IDENTITY_PIDS.get((fmtid, pid))
    if kind is None and fmtid == INV_DESIGN_TRACKING:
        kind = INV_PEOPLE_PIDS.get(pid)
    if kind is None and fmtid.startswith("d861fb30") and pid == 16:
        kind = "account"
    if kind is None and fmtid.startswith("3d38de39"):  # Inventor Summary Information
        kind = {4: "person", 8: "account"}.get(pid)
    if kind is None and fmtid.startswith("8cf58000"):  # Inventor Document Summary Information
        kind = {14: "person", 15: "company"}.get(pid)
    return kind


def rewrite_fields(body: bytes, mapper) -> bytes:
    """Same-length pseudonymisation of identity fields (author, last saved by, ...) in one
    property-set stream, using the stream's own code page (cp1252 accents included)."""
    from deid.registry.pseudonym import norm

    buf = None
    for fmtid, pid, val, (off, nbytes, enc) in parse(body, positions=True):
        if not _kind(fmtid, pid) or norm(val) not in mapper.entries:
            continue
        try:
            raw = body[off:off + nbytes]
            text = raw.decode(enc)
            rep = text.replace(val, mapper.pseudonym(val)).encode(enc)
        except (UnicodeError, LookupError, KeyError):
            continue
        if len(rep) == nbytes and rep != raw:
            if buf is None:
                buf = bytearray(body)
            buf[off:off + nbytes] = rep
    return bytes(buf) if buf is not None else body


def harvest(data: bytes) -> list[tuple[str, str]]:
    import olefile

    out: list[tuple[str, str]] = []
    try:
        ole = olefile.OleFileIO(io.BytesIO(data))
    except Exception:
        return out
    try:
        for entry in ole.listdir(streams=True, storages=False):
            if not entry[-1].startswith("\x05"):
                continue
            try:
                body = ole.openstream(entry).read()
            except Exception:
                continue
            for fmtid, pid, s in parse(body):
                kind = _kind(fmtid, pid)
                if kind:
                    out.append((s, kind + "_field"))
    finally:
        ole.close()
    return out


def dump(data: bytes) -> list[tuple[str, str, int, str]]:
    """Debug helper: every string property with its stream and pid."""
    import olefile

    ole = olefile.OleFileIO(io.BytesIO(data))
    res = []
    for entry in ole.listdir(streams=True, storages=False):
        if entry[-1].startswith("\x05"):
            for fmtid, pid, s in parse(ole.openstream(entry).read()):
                res.append(("/".join(entry)[1:12], fmtid[:8], pid, s[:60]))
    return res
