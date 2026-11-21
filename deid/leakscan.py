"""Shadow scorer: count global identities still present in the output corpus.

Scans raw bytes (ASCII + UTF-16LE), the contents of zip containers and the
decoded streams of PDFs, and every path. Reports totals per file extension and
the most frequent leaking identities (printed locally, never published).
"""

from __future__ import annotations

import io
import os
import sys
import zipfile
from collections import Counter
from multiprocessing import Pool

from deid.harvest import ext_of, list_files
from deid.rewrite import load_mappers

G: dict = {}


def _init(reg, secret):
    G["allm"], G["content"] = load_mappers(reg, secret)


def _scan_bytes(data: bytes, m) -> Counter:
    c: Counter = Counter()
    for enc in ("ascii", "utf-16-le"):
        for _, _, key in m.find(data, enc):
            c[key] += 1
    return c


def scan_file(args):
    root, rel = args
    m = G["content"]
    c = Counter()
    for _, _, key in m.find(rel.encode("utf-8", "replace")):
        c["PATH:" + key] += 1
    p = os.path.join(root, rel)
    try:
        if os.path.getsize(p) > 1_500_000_000:
            return rel, c
        data = open(p, "rb").read()
    except OSError:
        return rel, c
    c += _scan_bytes(data, m)
    if data[:4] == b"PK\x03\x04":
        try:
            z = zipfile.ZipFile(io.BytesIO(data))
            for info in z.infolist():
                if info.file_size < 200_000_000:
                    c += _scan_bytes(info.filename.encode() + z.read(info), m)
        except Exception:
            pass
    elif data[:4] == b"%PDF":
        try:
            import pikepdf

            pdf = pikepdf.open(io.BytesIO(data))
            for obj in pdf.objects:
                if isinstance(obj, pikepdf.Stream):
                    try:
                        c += _scan_bytes(obj.read_bytes(), m)
                    except Exception:
                        pass
        except Exception:
            pass
    return rel, c


def run(out_root: str, reg: str, secret: bytes, workers=None) -> None:
    files = list_files(out_root)
    by_ext: Counter = Counter()
    files_ext: Counter = Counter()
    keys: Counter = Counter()
    with Pool(workers or os.cpu_count(), initializer=_init, initargs=(reg, secret)) as pool:
        for rel, c in pool.imap_unordered(scan_file, [(out_root, f) for f in files], chunksize=32):
            if c:
                e = ext_of(rel)
                by_ext[e] += sum(c.values())
                files_ext[e] += 1
                keys.update(c)
    print(f"files scanned: {len(files)}; files with leaks: {sum(files_ext.values())}", file=sys.stderr)
    print("leaky files by ext:", files_ext.most_common(25), file=sys.stderr)
    print("top leaking identities:", keys.most_common(40), file=sys.stderr)
