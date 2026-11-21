"""Local checker modelled on the challenge.pdf requirements.

Scores a de-identified corpus against its input on a held-out sample of
repositories (hash bucket 0 of 5, never used for tuning). Three families:

* found:  every input file has exactly one output with the same extension
          and the same directory depth;
* usable: geometry-preserving fingerprint equal to the input's
          (deid/fingerprint.py: STEP DATA with strings masked, STL triangles,
          OBJ v/f, IGES D+P with Hollerith masked, DXF non-text groups, PDF
          pages+boxes, OLE stream sizes, zip members recursively);
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
from deid.fingerprint import fingerprint
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
    res = {"found": 0, "usable": 0, "deid": 0, "deid_strict": 0, "ind": {}, "ext": ext_of(rel)}
    src, dst = os.path.join(in_root, rel), os.path.join(out_root, new_rel)
    if not os.path.exists(dst) or ext_of(new_rel) != ext_of(rel) or new_rel.count("/") != rel.count("/"):
        return res
    res["found"] = 1
    try:
        a, b = open(src, "rb").read(), open(dst, "rb").read()
        try:
            sa = fingerprint(a, res["ext"])
        except Exception:
            sa = ("invalid-input",)
        try:
            sb = fingerprint(b, res["ext"])
        except Exception:
            sb = ("invalid-output",)
        res["usable"] = int(sa == sb or sa == ("invalid-input",))
    except Exception:
        pass
    _, leaks = scan_file((out_root, new_rel))
    reg = {k: v for k, v in leaks.items() if not k.startswith("IND:")}
    content = {k: v for k, v in reg.items() if not k.startswith("PATH:")}
    res["deid"] = int(not content)
    res["path_deid"] = int(len(content) == len(reg))
    res["deid_strict"] = int(not leaks)
    res["leaks"] = sum(content.values())
    res["ind"] = {k[4:]: v for k, v in leaks.items() if k.startswith("IND:")}
    return res


def run(in_root: str, out_root: str, results_json: str, reg: str, secret: bytes, n: int = 3000,
        workers=None) -> dict:
    mapping = {r: nr for r, nr, _ in json.loads(Path(results_json).read_text())}
    files = [f for f in list_files(in_root) if held_out(f)]
    random.Random(1234).shuffle(files)
    files = files[:n]
    tot = Counter()
    ind_tot: Counter = Counter()
    by_ext: dict = {}
    with Pool(workers or os.cpu_count(), initializer=leak_init, initargs=(reg, secret)) as pool:
        for r in pool.imap_unordered(check_one, [(in_root, out_root, f, mapping.get(f, f)) for f in files],
                                     chunksize=16):
            for k in ("found", "usable", "deid", "path_deid", "deid_strict"):
                tot[k] += r.get(k, 0)
            ind_tot.update(r.get("ind", {}))
            c = by_ext.setdefault(r["ext"], Counter())
            c["n"] += 1
            c["usable"] += r["usable"]
            c["deid"] += r["deid"]
    N = len(files)
    rates = {k: tot[k] / N for k in ("found", "usable", "deid", "path_deid", "deid_strict")}
    score = round(1000 * (0.15 * rates["found"] + 0.15 * rates["usable"] + 0.70 * rates["deid"] * rates["usable"]))
    strict = round(1000 * (0.15 * rates["found"] + 0.15 * rates["usable"]
                           + 0.70 * rates["deid_strict"] * rates["usable"]))
    print(f"held-out files: {N}  found={rates['found']:.4f} usable={rates['usable']:.4f} "
          f"deid(content)={rates['deid']:.4f} deid(path)={rates['path_deid']:.4f} "
          f"deid_strict={rates['deid_strict']:.4f}  LOCAL SCORE={score}  STRICT SCORE={strict}", file=sys.stderr)
    print("independent findings by kind:", ind_tot.most_common(20), file=sys.stderr)
    from deid import consistency

    dg, dok, dbad = consistency.duplicates(in_root, out_root, mapping, files)
    rc, rok, rbad = consistency.references(in_root, out_root, mapping, files)
    rates["dup_consistent"] = dok / dg if dg else 1.0
    rates["refs_resolved"] = rok / rc if rc else 1.0
    print(f"duplicate groups: {dok}/{dg} consistent; references: {rok}/{rc} resolve after renames",
          file=sys.stderr)
    for x in dbad[:5]:
        print("  inconsistent duplicates:", x, file=sys.stderr)
    for x in rbad[:5]:
        print("  broken reference:", x, file=sys.stderr)
    worst = sorted(by_ext.items(), key=lambda kv: -(kv[1]["n"] - kv[1]["deid"]))[:12]
    for e, c in worst:
        print(f"  {e or '(none)'}: n={c['n']} usable={c['usable']} deid={c['deid']}", file=sys.stderr)
    return {"score": score, "strict": strict, **rates}
