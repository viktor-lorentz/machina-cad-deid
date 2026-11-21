#!/usr/bin/env python3
"""NER pass (agent C): raise identity recall with a zero-shot NER model (GLiNER).

Read-only research tool. Never commit its outputs (they contain originals).

Stages (each restartable; outputs in --work):
  extract   all PDF page text + PDF/OLE/zip metadata + text-like files (STEP/IGES headers, SVG text,
            DXF text, comments, plain text) -> chunks of <=~220 words, de-duplicated globally
            -> chunks.jsonl  {"h", "text", "src", "fids"}
  pack      line-level de-dup (title blocks repeat), drop numeric lines, STEP header literals only
            -> packed.jsonl {"h", "src", "text", "lines": [[offset, fids]]}
  ner       GLiNER over unique chunks, N worker processes x 1 torch thread -> preds.jsonl
  report    aggregate by (label, value), drop engineering terms / units / materials / standards
            bodies / well-known software, cross-check the registry -> ner_candidates.tsv

Usage on the VM:
  /data/ner/venv/bin/python tools/nerpass.py all /data/input /data/ner/work \
      --out /data/registry/ner_candidates.tsv --registry /data/registry/registry12.json --procs 32
Deps (pinned): see the `ner` extra in pyproject.toml.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import multiprocessing as mp
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import typeharvest as th  # noqa: E402  (shared extractors + engineering filters)

MODEL = os.environ.get("NER_MODEL", "urchade/gliner_multi_pii-v1")
MAX_PDF_PAGES = 400
CHUNK_WORDS = 220
THRESH = 0.45
# GLiNER prompt label -> output label
LABELS = {
    "person": "person",
    "company": "organization",
    "organization": "organization",
    "university or institute": "organization",
    "project name": "project",
    "product or part number": "partno",
    "street address": "address",
    "phone number": "phone",
    "email address": "email",
    "website or domain": "website",
    "username": "username",
}

# ------------------------------------------------------------------ extract
def segments(path: str, rel: str):
    """Yield (src, text) for one file. Text-bearing parts only."""
    ext = rel.rsplit(".", 1)[-1].lower() if "." in rel else ""
    if ext == "pdf":
        import fitz
        try:
            doc = fitz.open(path)
        except Exception:
            return
        try:
            md = doc.metadata or {}
            yield "pdfmeta", "\n".join(f"{k}: {v}" for k, v in md.items() if v)
            try:
                yield "pdfxmp", re.sub(r"<[^>]+>", " ", doc.get_xml_metadata() or "")
            except Exception:
                pass
            for i, page in enumerate(doc):
                if i >= MAX_PDF_PAGES:
                    break
                try:
                    yield "pdftext", page.get_text("text")
                except Exception:
                    pass
        finally:
            doc.close()
        return
    sz = os.path.getsize(path)
    with open(path, "rb") as f:
        head = f.read(th.HEAD * 4)
    if head[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        yield "olemeta", th.meta_ole(path)
        return
    if head[:2] == b"PK" and ext in ("fcstd", "3mf", "docx", "xlsx", "pptx", "f3d"):
        yield "zipmeta", th.meta_zipxml(path)
        return
    if ext not in th.TEXT_HEAD_EXT:
        return
    txt = head.decode("utf-8", "ignore")
    if ext in ("step", "stp"):
        yield "stephdr", txt.split("ENDSEC;")[0]
    elif ext in ("igs", "iges"):
        yield "igeshdr", "\n".join(l[:72] for l in txt.splitlines() if l[72:73] in ("S", "G"))
    elif ext == "svg":
        yield "svgtext", "\n".join(next(g for g in m.groups() if g) for m in th.SVG_KEEP.finditer(txt))
    elif ext in ("obj", "wrl", "vrml", "scad", "gcode", "nc", "sat", "x_t"):
        yield "comments", "\n".join(l for l in txt.splitlines() if l.lstrip().startswith(("#", "//", ";")))
    elif ext == "dxf":
        ls = txt.splitlines()
        yield "dxftext", "\n".join(ls[i + 1] for i in range(len(ls) - 1) if ls[i].strip() in ("999", "1", "3"))
    else:
        yield "text", txt if sz <= th.HEAD * 4 else txt[: th.HEAD * 4]


def chunk(text: str):
    """Split on line boundaries into pieces of <= CHUNK_WORDS words."""
    out, cur, n = [], [], 0
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        w = len(line.split())
        if w > CHUNK_WORDS:  # very long line: hard split
            words = line.split()
            for i in range(0, len(words), CHUNK_WORDS):
                out.append(" ".join(words[i:i + CHUNK_WORDS]))
            continue
        if n + w > CHUNK_WORDS and cur:
            out.append("\n".join(cur))
            cur, n = [], 0
        cur.append(line)
        n += w
    if cur:
        out.append("\n".join(cur))
    return out


def extract_one(item):
    fid, path, rel = item
    res = []
    try:
        for src, text in segments(path, rel):
            if not text or not re.search(r"[A-Za-z]{2}", text):
                continue
            for c in chunk(text):
                if len(c) >= 6 and re.search(r"[A-Za-z]{3}", c):
                    res.append((hashlib.blake2b(c.encode(), digest_size=12).hexdigest(), src, c))
    except Exception:
        pass
    return fid, res


def stage_extract(a):
    items = []
    for root, dirs, files in os.walk(a.input):
        dirs.sort()
        for fn in sorted(files):
            p = os.path.join(root, fn)
            items.append((len(items), p, os.path.relpath(p, a.input)))
    print(f"files: {len(items)}", flush=True)
    with open(os.path.join(a.work, "files.tsv"), "w") as f:
        for fid, _, rel in items:
            f.write(f"{fid}\t{rel}\n")
    chunks: dict = {}
    with mp.Pool(a.procs) as pool:
        for n, (fid, res) in enumerate(pool.imap_unordered(extract_one, items, chunksize=8), 1):
            for h, src, c in res:
                r = chunks.get(h)
                if r is None:
                    chunks[h] = [c, src, {fid}]
                else:
                    r[2].add(fid)
            if n % 10000 == 0:
                print(f"extract {n}/{len(items)} unique_chunks={len(chunks)}", flush=True)
    with open(os.path.join(a.work, "chunks.jsonl"), "w") as f:
        for h, (c, src, fids) in chunks.items():
            f.write(json.dumps({"h": h, "text": c, "src": src, "fids": sorted(fids)}) + "\n")
    print(f"unique chunks: {len(chunks)}", flush=True)

# ------------------------------------------------------------------ pack
# Title blocks, headers and XMP repeat across thousands of pages/files. NER cost is per word, so
# de-duplicate at LINE level (keeping each line's file set), drop numeric/geometry lines, and repack
# the surviving lines (in source order, so neighbouring context stays together) into chunks.
ALPHA3 = re.compile(r"[A-Za-z]{3}")
XMP_JUNK = re.compile(r"uuid:|xmp\.[id]id|adobe:docid|\b\d{4}-\d\d-\d\dT\d|^[\w.:/-]*$")
STEP_LIT = re.compile(r"'([^']{2,})'")


def lines_of(src: str, text: str):
    for line in text.split("\n"):
        if src == "stephdr":
            for lit in STEP_LIT.findall(line):
                yield lit.strip()
            continue
        if src == "pdfxmp" and XMP_JUNK.search(line.strip()):
            continue
        yield line.strip()


def stage_pack(a):
    line_fids: dict = {}
    order = []  # (src, line) first-seen order
    with open(os.path.join(a.work, "chunks.jsonl")) as f:
        for raw in f:
            r = json.loads(raw)
            for line in lines_of(r["src"], r["text"]):
                if len(line) < 3 or not ALPHA3.search(line):
                    continue
                if sum(c.isalpha() for c in line) < 0.3 * len(line):
                    continue
                k = line.lower()
                s = line_fids.get(k)
                if s is None:
                    line_fids[k] = s = set()
                    order.append((r["src"], line, k))
                s.update(r["fids"])
    n = chars = 0
    with open(os.path.join(a.work, "packed.jsonl"), "w") as f:
        cur, cur_src, words = [], None, 0

        def flush():
            nonlocal n, chars
            if not cur:
                return
            text, lines, off = [], [], 0
            for line, k in cur:
                lines.append([off, sorted(line_fids[k])])
                text.append(line)
                off += len(line) + 1
            t = "\n".join(text)
            f.write(json.dumps({"h": f"p{n}", "src": cur_src, "text": t, "lines": lines}) + "\n")
            n += 1
            chars += len(t)

        for src, line, k in order:
            w = len(line.split())
            if cur and (src != cur_src or words + w > CHUNK_WORDS):
                flush()
                cur, words = [], 0
            cur_src = src
            cur.append((line[:2000], k))
            words += w
        flush()
    print(f"packed: {len(line_fids)} unique lines -> {n} chunks, {chars} chars", flush=True)

# ------------------------------------------------------------------ ner
_M = None


def ner_init(model_dir):
    global _M
    import torch
    torch.set_num_threads(1)
    from gliner import GLiNER
    _M = GLiNER.from_pretrained(model_dir, local_files_only=True)
    _M.eval()


def ner_batch(batch):
    import torch
    labels = list(LABELS)
    out = []
    with torch.inference_mode():
        try:
            preds = _M.batch_predict_entities([b["text"] for b in batch], labels, threshold=THRESH)
        except Exception:
            preds = []
            for b in batch:
                try:
                    preds.append(_M.predict_entities(b["text"], labels, threshold=THRESH))
                except Exception:
                    preds.append([])
    for b, ents in zip(batch, preds):
        out.append({"h": b["h"], "ents": [[e["label"], e["text"], e["start"], e["end"], round(float(e["score"]), 3)]
                                          for e in ents]})
    return out


def stage_ner(a):
    from huggingface_hub import snapshot_download
    model_dir = snapshot_download(MODEL, cache_dir=os.path.join(a.work, "hf"))
    done = set()
    pp = os.path.join(a.work, "preds.jsonl")
    if os.path.exists(pp):
        with open(pp) as f:
            for line in f:
                try:
                    done.add(json.loads(line)["h"])
                except Exception:
                    pass
    todo = []
    with open(os.path.join(a.work, "packed.jsonl")) as f:
        for line in f:
            r = json.loads(line)
            if r["h"] not in done:
                todo.append({"h": r["h"], "text": r["text"]})
    # long chunks first so the tail of the run is not one slow worker
    todo.sort(key=lambda r: -len(r["text"]))
    batches = [todo[i:i + 8] for i in range(0, len(todo), 8)]
    print(f"ner: {len(todo)} chunks to do ({len(done)} done), {len(batches)} batches, model {MODEL}", flush=True)
    with mp.get_context("spawn").Pool(a.procs, initializer=ner_init, initargs=(model_dir,)) as pool, open(pp, "a") as f:
        for n, res in enumerate(pool.imap_unordered(ner_batch, batches), 1):
            for r in res:
                f.write(json.dumps(r) + "\n")
            if n % 200 == 0:
                f.flush()
                print(f"ner {n}/{len(batches)}", flush=True)

# ------------------------------------------------------------------ report
STD_BODIES = re.compile(r"^(ISO|ASTM|DIN|ANSI|ASME|IEC|IEEE|SAE|JIS|BSI?|NEMA|UL|CSA|NFPA|API|AISI|GOST|ECSS|NASA|"
                        r"ESA|NIST|CEN|CENELEC|VDI|VDE|ETSI|ITU|W3C|IETF|OSHA|EPA|FCC|RoHS|REACH|CE|SI|IPC|JEDEC|"
                        r"AWS|AGMA|ABMA|NPT|UNC|UNF|DoD|MIL)\b", re.I)
SOFTWARE_W = re.compile(r"\b" + th.SOFTWARE.pattern + r"\b", re.I)
SOFT_VENDOR = re.compile(r"\b(autodesk|dassault|syst[eè]mes|ptc|mathworks|microsoft|adobe|apple|google|oracle|spatial corp|"
                         r"siemens (plm|industry software|digital)|bentley systems|trimble|open ?cascade|github|gitlab|"
                         r"mcneel|graphisoft|nemetschek|hexagon|ansys|altair|esri|elysium|tech soft 3d|theorem solutions)\b", re.I)
AUTONAME = re.compile(r"^(?=[A-Za-z_]*[a-z])[A-Za-z]{3,}(?:_+[A-Za-z]+)*_*\d{2,4}$")     # Part__Feature024, Sketch012, Body001
GENERIC = {"inc", "ltd", "llc", "gmbh", "corp", "company", "university", "institute", "department", "dept", "lab",
           "laboratory", "group", "team", "project", "client", "customer", "designer", "drawn", "checked", "approved",
           "author", "engineer", "owner", "user", "admin", "name", "title", "date", "scale", "sheet", "rev", "revision",
           "material", "finish", "weight", "qty", "quantity", "description", "part", "assembly", "drawing", "unknown",
           "none", "n/a", "na", "tbd", "www", "http", "https", "com", "org", "the", "and", "of", "for", "page"}


def norm(label: str, v: str) -> str:
    v = re.sub(r"\s+", " ", v).strip(" \t.,;:()[]{}<>\"'|*-_/\\")
    if label in ("email", "website", "username"):
        v = v.lower()
    return v


def keep(label: str, v: str) -> bool:
    if len(v) < 3 or len(v) > 80:
        return False
    vl = v.lower()
    if vl in GENERIC or vl in th.TECH_WORDS or vl in th.UNITS:
        return False
    if not re.search(r"[A-Za-z]", v) and label not in ("phone", "partno"):
        return False
    if th.engineering(v):
        return False
    if label in ("person", "organization", "project", "partno") and SOFTWARE_W.search(v):
        return False
    if STD_BODIES.match(v):
        return False
    if label in ("website", "email"):
        host = re.sub(r"^[a-z]+://", "", vl).split("@")[-1].split("/")[0].split(":")[0].removeprefix("www.")
        if th.PUBLIC_HOSTS.search(host) or SOFT_VENDOR.search(host.replace(".", " ")):
            return False
    if label in ("organization", "person", "project") and SOFT_VENDOR.search(v):
        return False
    if label in ("partno", "project") and AUTONAME.match(v) and not re.search(r"\d{5,}", v):
        return False
    if label == "phone" and not th.PHONE_STRICT.match(v) and len(re.sub(r"\D", "", v)) < 7:
        return False
    if label == "email" and not th.EMAIL.fullmatch(vl):
        return False
    if label in ("person", "organization", "project"):
        toks = re.findall(r"[A-Za-z]+", v)
        if not toks:
            return False
        # a single lower-case dictionary word is never a name
        if len(toks) == 1 and (v.islower() or th.in_dict(toks[0])) and not th.INVENTED.fullmatch(toks[0]):
            return False
        # all-dictionary lower-case phrases (e.g. "stainless steel bolt") are engineering text
        if v.islower() and all(th.in_dict(t) for t in toks):
            return False
        if th.FC_DEFAULT.match(v):
            return False
    if label == "partno":
        if not re.search(r"\d", v) or th.DIMENSION.match(v) or th.MATERIALS.match(v) or re.fullmatch(r"[\d.,\s/-]+", v) and len(v) < 6:
            return False
    return True


def stage_report(a):
    th.DICT = th.load_dict()
    reg = set()
    if a.registry:
        for ident in json.load(open(a.registry))["identities"]:
            reg.add(ident["value"].lower())
    import bisect
    chunk_meta = {}
    with open(os.path.join(a.work, "packed.jsonl")) as f:
        for line in f:
            r = json.loads(line)
            chunk_meta[r["h"]] = (r["text"], r["src"], r["lines"])
    agg = {}
    with open(os.path.join(a.work, "preds.jsonl")) as f:
        for line in f:
            r = json.loads(line)
            text, src, lines = chunk_meta.get(r["h"], ("", "", [[0, []]]))
            offs = [o for o, _ in lines]
            for lab, val, s, e, sc in r["ents"]:
                fids = lines[max(0, bisect.bisect_right(offs, s) - 1)][1]
                lab = LABELS.get(lab, lab)
                v = norm(lab, val)
                if not keep(lab, v):
                    continue
                k = (lab, v)
                g = agg.get(k)
                if g is None:
                    g = agg[k] = [0, set(), collections.Counter(), [], 0.0, 0]
                g[0] += len(fids)          # occurrences weighted by how many files carry the chunk
                g[1].update(fids)
                g[2][src] += 1
                g[4] += sc
                g[5] += 1
                if len(g[3]) < 3:
                    c = th.ctx(text, s, e)
                    if c not in g[3]:
                        g[3].append(c)
    rows = []
    for (lab, v), (occ, fids, srcs, cx, ssum, n) in agg.items():
        if len(fids) < a.min_files:
            continue
        vl = v.lower()
        parts = [w for w in re.split(r"[\s._/@-]+", vl) if len(w) > 3]
        inreg = "full" if vl in reg else ("part" if any(w in reg for w in parts) else "")
        rows.append((lab, v, occ, len(fids), round(ssum / n, 3),
                     "|".join(f"{s}:{c}" for s, c in srcs.most_common()), inreg, " ¦ ".join(cx)))
    rows.sort(key=lambda r: (r[0], r[6] == "full", -r[3], -r[2]))
    with open(a.out, "w") as f:
        f.write("label\tvalue\tcount\tfiles\tmean_score\tsources\tin_registry\tcontexts\n")
        for r in rows:
            f.write("\t".join(str(x).replace("\t", " ").replace("\n", " ⏎ ") for x in r) + "\n")
    # drop-in for B's gate: `python gt_recall.py <registry> --add ner_candidates.add.tsv` (kind<TAB>value)
    with open(os.path.splitext(a.out)[0] + ".add.tsv", "w") as f:
        for r in rows:
            if r[6] != "full":
                f.write(f"{r[0]}\t{r[1]}\n")
    summ = collections.defaultdict(lambda: [0, 0, 0, 0])
    for r in rows:
        s = summ[r[0]]
        s[0] += 1
        s[1] += r[2]
        s[2] += r[6] != "full"
        s[3] += r[6] == "" and r[3] >= 2
    lines = ["label\tdistinct\tcount\tnot_full_in_registry\tnone_in_reg_files>=2"]
    lines += [f"{t}\t" + "\t".join(map(str, summ[t])) for t in sorted(summ)]
    with open(os.path.splitext(a.out)[0] + ".summary.txt", "w") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["extract", "pack", "ner", "report", "all"])
    ap.add_argument("input")
    ap.add_argument("work")
    ap.add_argument("--out", default="/data/registry/ner_candidates.tsv")
    ap.add_argument("--registry")
    ap.add_argument("--procs", type=int, default=32)
    ap.add_argument("--min-files", type=int, default=1)
    a = ap.parse_args()
    os.makedirs(a.work, exist_ok=True)
    if a.stage in ("extract", "all"):
        stage_extract(a)
    if a.stage in ("pack", "all"):
        stage_pack(a)
    if a.stage in ("ner", "all"):
        stage_ner(a)
    if a.stage in ("report", "all"):
        stage_report(a)


if __name__ == "__main__":
    main()
