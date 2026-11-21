"""Same-length in-place rewriting of OLE (Compound File) streams.

olefile cannot write streams stored in the mini-stream (all streams < 4096
bytes, which includes the property sets holding author / last-saved-by).
Because our pseudonyms never change byte length, we can map every byte of a
stream to its absolute file offset (via the FAT or the mini-FAT + mini-stream
chain) and patch the file buffer directly. Every sector, FAT and directory
entry stays exactly as it was.
"""

from __future__ import annotations

import io

import olefile


def _chain(fat, start: int, limit: int) -> list[int]:
    out, s = [], start
    while s not in (olefile.ENDOFCHAIN, olefile.FREESECT) and s >= 0 and len(out) < limit:
        out.append(s)
        if s >= len(fat):
            break
        s = fat[s]
    return out


def stream_offsets(ole: olefile.OleFileIO, sid: int) -> list[tuple[int, int]]:
    """(file_offset, length) runs covering the stream's bytes, in order."""
    entry = ole.direntries[sid]
    size = entry.size
    ss = ole.sectorsize
    if size < ole.minisectorcutoff and entry.entry_type == olefile.STGTY_STREAM:
        mss = ole.minisectorsize
        root = ole.root
        root_chain = _chain(ole.fat, root.isectStart, len(ole.fat) + 1)
        if ole.minifat is None:
            ole.loadminifat()
        mini = _chain(ole.minifat, entry.isectStart, len(ole.minifat) + 1)
        runs = []
        left = size
        for m in mini:
            pos = m * mss  # offset inside the mini-stream
            sec = root_chain[pos // ss]
            off = (sec + 1) * ss + pos % ss
            n = min(mss, left)
            runs.append((off, n))
            left -= n
            if left <= 0:
                break
        return runs
    runs = []
    left = size
    for sec in _chain(ole.fat, entry.isectStart, len(ole.fat) + 1):
        n = min(ss, left)
        runs.append(((sec + 1) * ss, n))
        left -= n
        if left <= 0:
            break
    return runs


def rewrite(data: bytes, transform) -> bytes:
    """Apply a same-length `transform(name_path, bytes) -> bytes` to every stream."""
    ole = olefile.OleFileIO(io.BytesIO(data))
    buf = bytearray(data)
    changed = False
    for sid, entry in enumerate(ole.direntries):
        if entry is None or entry.entry_type != olefile.STGTY_STREAM or entry.size == 0:
            continue
        if entry.size > 16_000_000:
            continue
        runs = stream_offsets(ole, sid)
        body = b"".join(bytes(buf[o:o + n]) for o, n in runs)
        if len(body) != entry.size:
            continue
        new = transform(entry.name, body)
        if new == body or len(new) != len(body):
            continue
        p = 0
        for o, n in runs:
            buf[o:o + n] = new[p:p + n]
            p += n
        changed = True
    ole.close()
    if not changed:
        return data
    out = bytes(buf)
    chk = olefile.OleFileIO(io.BytesIO(out))  # structure must still parse identically
    n_before = len(olefile.OleFileIO(io.BytesIO(data)).listdir())
    if len(chk.listdir()) != n_before:
        raise ValueError("OLE directory changed")
    chk.close()
    return out
