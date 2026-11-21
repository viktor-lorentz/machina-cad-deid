"""Pass 1: collect identity candidates from the whole corpus.

Output: JSON with, per (value, kind), the number of files it appears in, the
formats it came from and a few example paths (kept private, never published).
"""

from __future__ import annotations

import json
import os
import re
import sys
from collections import Counter, defaultdict
from multiprocessing import Pool
from pathlib import Path

from deid import textscan
from deid.formats import meta, step

MAX_READ = 64 * 1024 * 1024
OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
TEXTLIKE = {"svg", "dxf", "obj", "wrl", "mtl", "txt", "md", "csv", "xml", "json", "html", "htm",
            "scad", "kicad_pcb", "kicad_sch", "ini", "cfg", "yaml", "yml", "gcode", "nc", "tex", "py"}


def ext_of(path: str) -> str:
    name = path.rsplit("/", 1)[-1]
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""


def path_identities(rel: str) -> list[tuple[str, str]]:
    """Identities encoded in the directory layout."""
    parts = rel.split("/")
    out: list[tuple[str, str]] = []
    if len(parts) >= 3 and parts[0] == "sources":
        src, seg = parts[1], parts[2]
        if src == "github":
            bits = seg.split("__")
            if bits:
                out.append((bits[0], "account"))
            if len(bits) >= 2:
                out.append((bits[1], "project"))
        elif src == "gitlab":
            bits = [b for b in seg.split("__") if b]
            if bits and bits[0].startswith("gitlab."):
                bits = bits[1:]
            if bits:
                out.append((bits[0], "account"))
            if len(bits) >= 2:
                out.append((bits[-1], "project"))
        elif src == "web":
            out.append((seg, "domain"))
        elif src == "catalog":
            out.append((seg, "project"))
    elif len(parts) >= 2 and parts[0] == "archives":
        bits = parts[1].rsplit(".", 1)[0].split("__")
        if bits:
            out.append((bits[0], "account"))
        if len(bits) >= 2:
            out.append((bits[1], "project"))
    return out


def harvest_file(args: tuple[str, str]) -> tuple[str, str, list[tuple[str, str]], str | None]:
    root, rel = args
    p = os.path.join(root, rel)
    e = ext_of(rel)
    cands: list[tuple[str, str]] = []
    defect = None
    try:
        size = os.path.getsize(p)
        if size == 0:
            return rel, e, path_identities(rel), "empty"
        with open(p, "rb") as f:
            data = f.read(MAX_READ)
        head = data[:16]
        if e in ("step", "stp", "p21") or head.startswith(b"ISO-10303-21"):
            cands += step.harvest(data)
            cands += textscan.scan(data[:200000])
        elif e == "pdf" or head.startswith(b"%PDF"):
            cands += meta.pdf(data)
            cands += textscan.scan(data[:2_000_000])
        elif e in ("igs", "iges"):
            cands += meta.iges(data)
            cands += textscan.scan(data[:40000])
        elif head.startswith(b"PK\x03\x04"):
            cands += meta.zipxml(data)
        elif head.startswith(OLE_MAGIC):
            cands += meta.ole(data)
            cands += textscan.scan(data)
        elif head.startswith(b"#UGC:"):
            cands += meta.creo(data)
        elif e == "dxf":
            cands += meta.dxf(data)
            cands += textscan.scan(data)
        elif e in TEXTLIKE or e == "stl" and head.startswith(b"solid"):
            cands += textscan.scan(data[:4_000_000])
        else:
            cands += textscan.scan(data[:1_000_000])
    except Exception as ex:  # noqa: BLE001
        defect = f"error:{type(ex).__name__}"
    cands += path_identities(rel)
    return rel, e, cands, defect


def list_files(root: str) -> list[str]:
    out = []
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if d != ".get-input"]
        for fn in fns:
            out.append(os.path.relpath(os.path.join(dp, fn), root))
    return sorted(out)


def run(root: str, out_path: str, workers: int | None = None) -> None:
    files = list_files(root)
    print(f"harvesting {len(files)} files", file=sys.stderr)
    df: Counter = Counter()
    fmts: dict = defaultdict(Counter)
    ex: dict = defaultdict(list)
    defects: dict[str, str] = {}
    with Pool(workers or os.cpu_count()) as pool:
        for i, (rel, e, cands, defect) in enumerate(
            pool.imap_unordered(harvest_file, [(root, f) for f in files], chunksize=64)
        ):
            if defect:
                defects[rel] = defect
            for key in set((re.sub(r"\s+", " ", v.strip()), k) for v, k in cands if v.strip()):
                df[key] += 1
                fmts[key][e] += 1
                if len(ex[key]) < 3:
                    ex[key].append(rel)
            if i % 20000 == 0:
                print(f"  {i}", file=sys.stderr)
    rows = [
        {"value": v, "kind": k, "files": n, "formats": dict(fmts[(v, k)].most_common(5)), "examples": ex[(v, k)]}
        for (v, k), n in df.most_common()
    ]
    Path(out_path).write_text(json.dumps({"candidates": rows, "defects": defects}, indent=1))
    print(f"{len(rows)} candidates, {len(defects)} defects -> {out_path}", file=sys.stderr)
