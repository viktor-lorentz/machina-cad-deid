"""Local checker modelled on the challenge.pdf requirements.

Scores a de-identified corpus against its input on a held-out sample of
repositories (hash bucket 0 of 5, never used for tuning). Three families:

* found:  every input file has exactly one output with the same extension
          and the same directory depth;
* usable: the output still parses like its input (STEP sections, PDF page
          count, zip member count + CRC, OLE stream list, STL size/facets,
          IGES section letters, DXF section count);
* deid:   no global registry identity remains in the output path, raw
          bytes (ASCII/UTF-16LE), zip members or decoded PDF streams.

Prints per-family pass rates and a combined score out of 1000.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import random
import sys
import zipfile
from collections import Counter
from multiprocessing import Pool
from pathlib import Path

from deid.harvest import ext_of, list_files
from deid.leakscan import _init as leak_init, scan_file

G: dict = {}


def repo_key(rel: str) -> str:
    parts = rel.split("/")
    return "/".join(parts[:3])


def held_out(rel: str) -> bool:
    return int(hashlib.md5(repo_key(rel).encode()).hexdigest(), 16) % 5 == 0


def _structure(data: bytes, e: str):
    """A format fingerprint that must survive de-identification."""
    if not data:
        return ("empty",)
    if data.startswith(b"ISO-10303-21"):
        return ("step", data.count(b"ENDSEC;"), b"END-ISO-10303-21" in data[-200:], len(data.split(b"\n#")))
    if data.startswith(b"%PDF"):
        import pikepdf

        with pikepdf.open(io.BytesIO(data)) as p:
            return ("pdf", len(p.pages))
    if data.startswith(b"PK\x03\x04"):
        z = zipfile.ZipFile(io.BytesIO(data))
        return ("zip", len(z.infolist()), z.testzip() is None)
    if data.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
        import olefile

        o = olefile.OleFileIO(io.BytesIO(data))
        n = len(o.listdir())
        o.close()
        return ("ole", n)
    if e == "stl":
        return ("stl", len(data), data.count(b"facet"))
    if e in ("igs", "iges"):
        return ("iges", tuple(sorted(Counter(l[72:73] for l in data.splitlines() if len(l) >= 73).items())))
    if e == "dxf":
        return ("dxf", data.count(b"SECTION"), data.count(b"EOF"))
    return ("bytes", len(data))


def check_one(args):
    in_root, out_root, rel, new_rel = args
    res = {"found": 0, "usable": 0, "deid": 0, "ext": ext_of(rel)}
    src, dst = os.path.join(in_root, rel), os.path.join(out_root, new_rel)
    if not os.path.exists(dst) or ext_of(new_rel) != ext_of(rel) or new_rel.count("/") != rel.count("/"):
        return res
    res["found"] = 1
    try:
        a, b = open(src, "rb").read(), open(dst, "rb").read()
        try:
            sa = _structure(a, res["ext"])
        except Exception:
            sa = ("invalid-input",)
        try:
            sb = _structure(b, res["ext"])
        except Exception:
            sb = ("invalid-output",)
        res["usable"] = int(sa == sb or sa == ("invalid-input",))
    except Exception:
        pass
    _, leaks = scan_file((out_root, new_rel))
    res["deid"] = int(not leaks)
    res["leaks"] = sum(leaks.values())
    return res


def run(in_root: str, out_root: str, results_json: str, reg: str, secret: bytes, n: int = 3000,
        workers=None) -> dict:
    mapping = {r: nr for r, nr, _ in json.loads(Path(results_json).read_text())}
    files = [f for f in list_files(in_root) if held_out(f)]
    random.Random(1234).shuffle(files)
    files = files[:n]
    tot = Counter()
    by_ext: dict = {}
    with Pool(workers or os.cpu_count(), initializer=leak_init, initargs=(reg, secret)) as pool:
        for r in pool.imap_unordered(check_one, [(in_root, out_root, f, mapping.get(f, f)) for f in files],
                                     chunksize=16):
            for k in ("found", "usable", "deid"):
                tot[k] += r[k]
            c = by_ext.setdefault(r["ext"], Counter())
            c["n"] += 1
            c["usable"] += r["usable"]
            c["deid"] += r["deid"]
    N = len(files)
    rates = {k: tot[k] / N for k in ("found", "usable", "deid")}
    score = round(1000 * (0.15 * rates["found"] + 0.15 * rates["usable"] + 0.70 * rates["deid"] * rates["usable"]))
    print(f"held-out files: {N}  found={rates['found']:.4f} usable={rates['usable']:.4f} "
          f"deid={rates['deid']:.4f}  LOCAL SCORE={score}", file=sys.stderr)
    worst = sorted(by_ext.items(), key=lambda kv: -(kv[1]["n"] - kv[1]["deid"]))[:12]
    for e, c in worst:
        print(f"  {e or '(none)'}: n={c['n']} usable={c['usable']} deid={c['deid']}", file=sys.stderr)
    return {"score": score, **rates}
