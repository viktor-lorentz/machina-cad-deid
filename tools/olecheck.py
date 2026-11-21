#!/usr/bin/env python3
"""Per-file OLE checker (agent C): saved-account + cross-stream residue, modelled on the grader's
"OLE saved-account" and "OLE cross-stream residue" checks.

For each sampled OLE input/output pair:
  A. saved-account: every identity field of the INPUT's property sets (SummaryInformation Author / LastSavedBy,
     DocumentSummaryInformation Manager / Company, Inventor design-tracking people, Inventor control last user,
     plus string values of custom/user-defined sets that look like names) must differ in the output, and the same
     input value must map to the same output value in every file.
  B. field residue: those input field values (len >= 3) must not appear ANYWHERE in the output file: every stream,
     as raw bytes, cp1252/latin-1, UTF-16LE, case-insensitive, and inside zlib streams (inflated at every zlib
     header) — including property sets of other FMTIDs, Header2 / ISolidWorksInformation / Contents / UFRxDoc /
     Solid Edge streams, previews (embedded text) and the directory entry names.
  C. registry residue: any registry original (global identities, len >= 5) in the same views.

Outputs: summary to stdout (no values); private per-file failures with values to --fail (never commit).
Usage (VM): /data/code/.venv/bin/python tools/olecheck.py /data/input /data/attempts/attempt-N/corpus \
    /data/attempts/attempt-N.results.json --registry /data/registry/registryX.json --n 200 \
    --fail /data/attempts/attempt-N.olecheck-failures.tsv
"""
from __future__ import annotations

import argparse
import collections
import io
import json
import os
import random
import re
import sys
import zlib

import olefile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from deid.formats import oleps  # noqa: E402

MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
ZHDR = re.compile(rb"\x78[\x01\x5e\x9c\xda]")
NAMEISH = re.compile(r"^[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ.'\- ]{1,40}$|^[\w.-]+\\[\w.-]+$|^[\w.+-]+@[\w.-]+$")
SKIP_VALUES = {"author", "owner", "user", "admin", "administrator", "default", "unknown", "none", "n/a", "na",
               "solidworks", "autodesk", "inventor", "solid edge", "microsoft", "true", "false", "yes", "no"}


def fields(data: bytes):
    """[(stream, fmtid, pid, kind, value)] identity-ish string properties of an OLE file."""
    out = []
    try:
        ole = olefile.OleFileIO(io.BytesIO(data))
    except Exception:
        return out
    try:
        for e in ole.listdir(streams=True, storages=False):
            if not e[-1].startswith("\x05"):
                continue
            try:
                body = ole.openstream(e).read()
            except Exception:
                continue
            for fmtid, pid, v in oleps.parse(body):
                kind = oleps._kind(fmtid, pid)
                if kind is None:
                    continue
                if v.strip().lower() in SKIP_VALUES or len(v.strip()) < 3:
                    continue
                out.append(("/".join(e), fmtid, pid, kind, v.strip()))
    finally:
        ole.close()
    return out


def views(data: bytes):
    """(where, lowercased text) views of every stream + dir names; zlib members inflated."""
    try:
        ole = olefile.OleFileIO(io.BytesIO(data))
    except Exception:
        yield "file", data.decode("latin-1").lower()
        return
    try:
        names = []
        for e in ole.listdir(streams=True, storages=True):
            names.append("/".join(e))
        yield "dirnames", "\n".join(names).lower()
        for e in ole.listdir(streams=True, storages=False):
            sname = "/".join(e)
            try:
                body = ole.openstream(e).read()
            except Exception:
                continue
            yield sname + ":raw", body.decode("latin-1").lower()
            yield sname + ":u16", body.decode("utf-16-le", "ignore").lower()
            if len(body) > 1:
                yield sname + ":u16o", body[1:].decode("utf-16-le", "ignore").lower()
            seen = 0
            for m in ZHDR.finditer(body):
                if seen > 64:
                    break
                try:
                    d = zlib.decompressobj()
                    inf = d.decompress(body[m.start():m.start() + 8_000_000], 32_000_000)
                except zlib.error:
                    continue
                if len(inf) < 16:
                    continue
                seen += 1
                yield f"{sname}:zlib@{m.start()}", inf.decode("latin-1").lower()
                yield f"{sname}:zlib@{m.start()}:u16", inf.decode("utf-16-le", "ignore").lower()
    finally:
        ole.close()


def enc_forms(v: str):
    """Lowercased search forms of a value as it would look in latin-1 decoded text."""
    v = v.lower()
    forms = {v}
    try:
        forms.add(v.encode("utf-8").decode("latin-1"))
    except UnicodeError:
        pass
    return forms


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("output")
    ap.add_argument("results")
    ap.add_argument("--registry")
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--fail", default="")
    ap.add_argument("--files", default="", help="optional list of input rel paths to check instead of sampling")
    a = ap.parse_args()

    pairs = [(r[0], r[1]) for r in json.load(open(a.results)) if isinstance(r, list) and len(r) >= 2]
    if a.files:
        want = {l.rstrip("\n") for l in open(a.files) if l.strip()}
        pairs = [p for p in pairs if p[0] in want]
    else:
        random.Random(a.seed).shuffle(pairs)
    reg = None
    if a.registry:
        import ahocorasick
        reg = ahocorasick.Automaton()
        for ident in json.load(open(a.registry))["identities"]:
            v = ident["value"].lower()
            if len(v) >= 5 and ident.get("scope", "global") == "global":
                reg.add_word(v, v)
        reg.make_automaton()

    stats = collections.Counter()
    mapping = collections.defaultdict(collections.Counter)  # input value -> output values (same field)
    where_hits = collections.Counter()
    kind_hits = collections.Counter()
    fails = []
    checked = 0
    for rin, rout in pairs:
        if checked >= a.n:
            break
        pin, pout = os.path.join(a.input, rin), os.path.join(a.output, rout)
        try:
            with open(pin, "rb") as f:
                if f.read(8) != MAGIC:
                    continue
            din = open(pin, "rb").read()
            dout = open(pout, "rb").read()
        except OSError:
            stats["missing_output"] += 1
            continue
        checked += 1
        fin = fields(din)
        fout = {(s, fm, p): v for s, fm, p, k, v in fields(dout)}
        if not fin:
            stats["no_identity_fields"] += 1
        acct_ok = True
        for s, fm, p, k, v in fin:
            ov = fout.get((s, fm, p))
            stats[f"field:{k}"] += 1
            if ov is None:
                stats[f"field_dropped:{k}"] += 1
                continue
            mapping[(k if k != "custom" else "custom", v)][ov] += 1
            if ov.lower() == v.lower():
                acct_ok = False
                stats[f"field_unchanged:{k}"] += 1
                fails.append(("A-unchanged", k, rin, s, f"{fm}:{p}", v))
        vs = {v for _, _, _, _, v in fin}
        resid = []
        reg_resid = []
        for where, text in views(dout):
            for v in vs:
                for fv in enc_forms(v):
                    i = text.find(fv)
                    while i >= 0:   # word-bounded: "map" inside "bitmap" is not residue
                        a0 = text[i - 1] if i else " "
                        b0 = text[i + len(fv)] if i + len(fv) < len(text) else " "
                        if not (a0.isalnum() and fv[0].isalnum()) and not (b0.isalnum() and fv[-1].isalnum()):
                            resid.append((where, v))
                            break
                        i = text.find(fv, i + 1)
                    else:
                        continue
                    break
            if reg is not None:
                for end, w in reg.iter(text):
                    st = end - len(w) + 1
                    a0 = text[st - 1] if st else " "
                    b0 = text[end + 1] if end + 1 < len(text) else " "
                    if (a0.isalnum() and w[0].isalnum()) or (b0.isalnum() and w[-1].isalnum()):
                        continue
                    reg_resid.append((where, w))
        resid = sorted(set(resid))
        if resid:
            stats["B_residue_files"] += 1
            for where, v in resid:
                where_hits[re.sub(r"\d+", "#", re.sub(r"@\d+", "", where))] += 1
                kk = next((k for _, _, _, k, x in fin if x == v), "?")
                kind_hits[kk] += 1
                fails.append(("B-residue", kk, rin, where, "", v))
        reg_resid = sorted(set(reg_resid))
        # registry residue counts only whole-token-ish hits (avoid substrings of longer words)
        if reg_resid:
            stats["C_registry_residue_files"] += 1
            for where, w in reg_resid[:20]:
                fails.append(("C-registry", "", rin, where, "", w))
        if fin:
            stats["A_files_with_fields"] += 1
            stats["A_pass"] += acct_ok
            stats["B_pass"] += not resid
            stats["AB_pass"] += acct_ok and not resid
    incons = sum(1 for k, c in mapping.items() if len(c) > 1)
    print(f"OLE files checked: {checked}")
    for k in sorted(stats):
        print(f"  {k}: {stats[k]}")
    n = max(1, stats["A_files_with_fields"])
    print(f"A saved-account pass: {stats['A_pass']}/{stats['A_files_with_fields']} = {stats['A_pass']/n:.3f}")
    print(f"B cross-stream residue pass: {stats['B_pass']}/{stats['A_files_with_fields']} = {stats['B_pass']/n:.3f}")
    print(f"A+B pass: {stats['AB_pass']/n:.3f};  inconsistent field mappings: {incons}/{len(mapping)}")
    print("residue by stream view:", where_hits.most_common(15))
    print("residue by field kind:", kind_hits.most_common())
    if a.fail:
        with open(a.fail, "w") as f:
            f.write("check\tkind\tinput\twhere\tprop\tvalue\n")
            for r in fails:
                f.write("\t".join(str(x).replace("\t", " ").replace("\n", " ") for x in r) + "\n")
            for (k, v), c in mapping.items():
                if len(c) > 1:
                    f.write(f"A-inconsistent\t{k}\t\t\t\t{v} -> {dict(c)}\n")


if __name__ == "__main__":
    main()
