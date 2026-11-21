"""Cross-file checks (agent B): duplicates and references.

* duplicates: input files with identical bytes must have identical outputs
  (same original identity -> same pseudonym, deterministically);
* references: when an input file mentions another input file's basename
  (assembly -> part, OBJ mtllib, drawing -> model, README links), the output
  must mention that file's *output* basename, so renamed links still resolve.
"""

from __future__ import annotations

import hashlib
import os
import re
from collections import defaultdict

_REF_EXT = ("stp", "step", "igs", "iges", "stl", "obj", "mtl", "sldprt", "sldasm", "slddrw", "ipt", "iam", "idw",
            "dwg", "dxf", "pdf", "fcstd", "3mf", "x_t", "x_b", "sat", "prt", "asm", "drw", "png", "jpg")
_TEXTY = ("stp", "step", "obj", "mtl", "txt", "md", "dxf", "igs", "iges", "xml", "json", "csv", "html", "scad", "urdf",
          "sdf", "yaml", "yml", "ini", "cfg", "lst", "bom")


def _sha(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def duplicates(in_root: str, out_root: str, mapping: dict, rels: list[str]) -> tuple[int, int, list]:
    """Returns (groups checked, groups consistent, examples of inconsistent output paths)."""
    by_size = defaultdict(list)
    for r in rels:
        try:
            by_size[os.path.getsize(os.path.join(in_root, r))].append(r)
        except OSError:
            pass
    groups = defaultdict(list)
    for size, rs in by_size.items():
        if len(rs) > 1 and size > 0:
            for r in rs:
                groups[_sha(os.path.join(in_root, r))].append(r)
    checked = ok = 0
    bad = []
    for rs in groups.values():
        if len(rs) < 2:
            continue
        checked += 1
        outs = set()
        for r in rs:
            p = os.path.join(out_root, mapping.get(r, r))
            outs.add(_sha(p) if os.path.exists(p) else "missing")
        if len(outs) == 1 and "missing" not in outs:
            ok += 1
        elif len(bad) < 10:
            bad.append([mapping.get(r, r) for r in rs])
    return checked, ok, bad


def references(in_root: str, out_root: str, mapping: dict, rels: list[str], limit: int = 2000):
    """Returns (refs checked, refs resolved, examples of broken output refs)."""
    by_dir = defaultdict(dict)  # top-3 repo key -> basename -> rel
    for r in mapping:
        b = r.rsplit("/", 1)[-1]
        if "." in b and b.rsplit(".", 1)[-1].lower() in _REF_EXT and len(b) >= 5:
            by_dir["/".join(r.split("/")[:3])][b] = r
    checked = ok = 0
    bad = []
    for r in rels:
        e = r.rsplit(".", 1)[-1].lower() if "." in r.rsplit("/", 1)[-1] else ""
        if e not in _TEXTY:
            continue
        names = by_dir.get("/".join(r.split("/")[:3]))
        if not names:
            continue
        try:
            src = open(os.path.join(in_root, r), "rb").read(5_000_000)
            dst = open(os.path.join(out_root, mapping.get(r, r)), "rb").read(6_000_000)
        except OSError:
            continue
        for base, target in names.items():
            if target == r:
                continue
            if re.search(rb"(?<![A-Za-z0-9_.-])" + re.escape(base.encode()) + rb"(?![A-Za-z0-9_-])", src):
                checked += 1
                new_base = mapping.get(target, target).rsplit("/", 1)[-1].encode()
                if new_base in dst:
                    ok += 1
                elif len(bad) < 10:
                    bad.append((mapping.get(r, r), new_base.decode("utf-8", "replace")))
                if checked >= limit:
                    return checked, ok, bad
    return checked, ok, bad
