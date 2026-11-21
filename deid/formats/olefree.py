"""Zero unallocated sectors of an OLE compound file.

CAD programs leave stale copies of earlier stream versions (old SummaryInformation with
author / last-saved-by, old Header2 ...) in sectors the FAT marks FREESECT, and in free
mini-sectors of the mini stream. They are not part of any stream, so zeroing them changes
no stream content, offsets or file length, but removes identity residue."""
from __future__ import annotations

import io

FREESECT = 0xFFFFFFFF


def scrub(data: bytes) -> bytes:
    import olefile

    try:
        ole = olefile.OleFileIO(io.BytesIO(data))
    except Exception:
        return data
    buf = None
    try:
        ss = ole.sectorsize
        nsec = (len(data) - 512 + ss - 1) // ss
        for i, nxt in enumerate(ole.fat[:nsec]):
            if nxt == FREESECT:
                off = 512 + i * ss
                chunk = data[off:off + ss]
                if chunk.strip(b"\x00"):
                    if buf is None:
                        buf = bytearray(data)
                    buf[off:off + len(chunk)] = b"\x00" * len(chunk)
        # free mini-sectors inside the mini stream (root entry chain)
        try:
            ole.loadminifat()
            minifat = ole.minifat
        except Exception:
            minifat = None
        root = ole.root
        if minifat is not None and root is not None and root.isectStart not in (FREESECT, 0xFFFFFFFE):
            chain, s = [], root.isectStart
            while s < len(ole.fat) and len(chain) < nsec:
                chain.append(s)
                s = ole.fat[s]
            mss = ole.minisectorsize
            for j, nxt in enumerate(minifat):
                if nxt != FREESECT:
                    continue
                pos = j * mss
                k, within = divmod(pos, ss)
                if k >= len(chain) or pos + mss > root.size:
                    continue
                off = 512 + chain[k] * ss + within
                chunk = data[off:off + mss]
                if chunk.strip(b"\x00"):
                    if buf is None:
                        buf = bytearray(data)
                    buf[off:off + mss] = b"\x00" * mss
    except Exception:
        return data
    finally:
        ole.close()
    if buf is None:
        return data
    out = bytes(buf)
    # self-check: same stream list and contents
    a, b = olefile.OleFileIO(io.BytesIO(data)), olefile.OleFileIO(io.BytesIO(out))
    try:
        for e in a.listdir(streams=True, storages=False):
            if a.openstream(e).read() != b.openstream(e).read():
                raise ValueError("olefree changed stream " + "/".join(e))
    finally:
        a.close()
        b.close()
    return out
