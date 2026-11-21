#!/usr/bin/env python3
"""Read-only harvester for identity TYPES the registry misses.

Scans file paths, format metadata (PDF Info/XMP, STEP/IGES headers, OLE
SummaryInformation, FCStd/3MF XML, raw head/tail strings) and PDF page text.
Emits candidates per type with counts and example contexts. Never writes into
the input. Output contains original identifiers: keep it on the VM, never commit.

Usage (VM):
  /data/code/.venv/bin/python tools/typeharvest.py /data/input /data/attempts/typeharvest \
      --registry /data/registry/registry5.json --procs 12 [--limit N]
"""
from __future__ import annotations

import argparse
import collections
import json
import multiprocessing as mp
import os
import re
import sys
import zipfile

HEAD = 65536
MAX_PDF_PAGES = 80
MAX_CTX = 3

# ---------------------------------------------------------------- filters
UNITS = {"mm", "cm", "m", "km", "in", "inch", "ft", "lb", "lbs", "kg", "g", "n", "nm", "kn", "mpa",
         "gpa", "psi", "ksi", "pa", "kpa", "hz", "khz", "mhz", "ghz", "v", "kv", "mv", "a", "ma", "w",
         "kw", "mw", "rpm", "deg", "rad", "s", "ms", "us", "c", "f", "k", "oz", "um", "mil", "mils", "dpi"}
STD_PREFIX = re.compile(
    r"^(ISO|ASTM|DIN|ANSI|ASME|EN|IEC|MIL|SAE|JIS|BS|UNC|UNF|NPT|AWS|IPC|NEMA|UL|CSA|GB|AS|AMS|NAS|MS|"
    r"AN|ISA|IEEE|NFPA|API|AISI|SS|AL|GOST|ECSS|NASA|STD|DOD|FED|RFC|USB|PCI|M\d|G\d|R\d|NEN|UNI|VDI)",
    re.I)
MATERIALS = re.compile(r"^(AL|SS|ST|CU|PLA|ABS|PETG|PEEK|POM|PTFE|PVC|HDPE|NYLON|PA\d*|AISI|S\d{3}|"
                       r"\d{4}-T\d+|T\d{3,4}|\d{3,4}[A-Z]?\d?)$", re.I)
DIMENSION = re.compile(r"^\d+([.,]\d+)?\s*(x|X|×)\s*\d+|^\d+([.,]\d+)?(mm|cm|in|m|deg|°)$|^M\d+(x\d+)?|"
                       r"^\d+-\d+\s*(UNC|UNF)|^#\d+-\d+", re.I)
DATE = re.compile(r"^(19|20)\d\d[-/.]\d\d?[-/.]\d\d?$|^\d\d?[-/.]\d\d?[-/.](19|20)?\d\d$")
HEXISH = re.compile(r"^[0-9a-f]{8,}$|^[0-9A-F]{8,}$")
SOFTWARE = re.compile(r"(solidworks|inventor|autocad|freecad|catia|creo|nx|parasolid|acis|opencascade|"
                      r"adobe|acrobat|microsoft|word|excel|latex|pdftex|ghostscript|cairo|skia|libre|"
                      r"openoffice|quartz|mac os|windows|linux|itext|reportlab|tcpdf|fpdf|chrome|firefox|"
                      r"inkscape|matlab|python|kicad|eagle|altium|fusion|onshape|rhino|blender|sketchup|"
                      r"solid edge|ansys|abaqus|comsol|step|iges|stl|pdf|xml|utf|unicode)", re.I)

def load_dict():
    words = set()
    for p in ("/usr/share/dict/american-english", "/usr/share/dict/words"):
        try:
            with open(p, encoding="utf-8", errors="ignore") as f:
                for w in f:
                    w = w.strip().lower()
                    if w.endswith("'s"):
                        w = w[:-2]
                    words.add(w)
        except OSError:
            pass
    return words

DICT: set = set()

def in_dict(w: str) -> bool:
    w = w.lower()
    if w in DICT:
        return True
    for suf in ("s", "es", "ed", "ing", "er", "ers", "ly", "al", "ion", "ions"):
        if w.endswith(suf) and w[: -len(suf)] in DICT:
            return True
    return False

def engineering(tok: str) -> bool:
    t = tok.strip(".,;:()[]{}\"'")
    if not t:
        return True
    if t.lower() in UNITS or STD_PREFIX.match(t) or MATERIALS.match(t) or DIMENSION.match(t) or DATE.match(t):
        return True
    if HEXISH.match(t):          # GUIDs / hashes
        return True
    return False

# ---------------------------------------------------------------- detectors
CV = "bcdfghjklmnprstvwxyz"
INVENTED = re.compile(rf"\b(?:[{CV}]?[aeiou]){{2,}}[{CV}]?\b", re.I)          # Zotakul, Uliredok
DOTTED = re.compile(r"\b[a-z]{2,8}(?:\.[a-z]{2,10}){1,3}\b")                    # ote.ipob.eka
URL = re.compile(r"\b(?:https?|ftp)://[^\s\"'<>)\]]+|\bwww\.[a-z0-9-]+(?:\.[a-z0-9-]+)+", re.I)
EMAIL = re.compile(r"\b[\w.+-]+@[a-z0-9-]+(?:\.[a-z0-9-]+)+\b", re.I)
TLDS = "com|org|net|edu|gov|io|de|uk|fr|es|it|nl|ch|se|no|dk|fi|jp|cn|au|nz|ca|us|ru|pl|cz|be|at|br|in|eu|info|biz|co"
HOST = re.compile(rf"\b(?:[a-z0-9-]{{2,}}\.)+(?:{TLDS})\b", re.I)
USERPATH = re.compile(r"(?:[A-Za-z]:\\(?:Users|Documents and Settings)\\|/home/|/Users/)([A-Za-z0-9._ -]{2,32}?)(?=[\\/])")
DOMUSER = re.compile(r"\b([A-Z][A-Z0-9-]{2,15})\\([A-Za-z][A-Za-z0-9._-]{1,24})\b")
PHONE = re.compile(r"(?<![\w.])(?:\+\d{1,3}[\s.-]?)?(?:\(\d{2,4}\)[\s.-]?|\d{2,4}[\s.-])\d{2,4}[\s.-]\d{2,5}(?:[\s.-]\d{2,4})?(?![\w.])")
PHONE_CTX = re.compile(r"(tel|phone|fax|ph|mobile|cell|t:|f:|telefon|tél|tlf|call)", re.I)
ADDRESS = re.compile(r"\b\d{1,5}\s+(?:[A-Z][a-z]+\.?\s+){1,4}(?:Street|St\.?|Avenue|Ave\.?|Road|Rd\.?|Boulevard|Blvd\.?|"
                     r"Drive|Dr\.?|Lane|Ln\.?|Way|Court|Ct\.?|Place|Pl\.?|Parkway|Pkwy|Highway|Hwy|Circle)\b"
                     r"|\b(?:[A-Z][a-zäöü]+)(?:straße|strasse|str\.|weg|platz|gasse)\s+\d{1,4}\b"
                     r"|\b(?:Calle|Carrer|Rue|Via|Avenida|Av\.)\s+[A-Z][\w ]{2,30}\d{0,4}"
                     r"|\b(?:Suite|Ste\.?|P\.?O\.? Box)\s+\d+\b"
                     r"|\b[A-Z][a-z]+,\s+[A-Z]{2}\s+\d{5}(?:-\d{4})?\b", re.U)
PARTLABEL = re.compile(r"(?:DWG|DRAWING|DRG|PART|DOC(?:UMENT)?|ITEM|ASSY|ASSEMBLY|P/N|PN|CAT(?:ALOG)?|ORDER|ART(?:ICLE)?|"
                       r"SKU|MODEL|REF|PROJECT|JOB)\s*(?:NO|NUM(?:BER)?|#|ID|CODE)?\.?\s*[:#]?\s*([A-Z0-9][A-Z0-9_./-]{3,30})", re.I)
# code-like tokens: letters + digits, dashes/underscores, len>=5
CODE = re.compile(r"\b(?=[A-Za-z0-9_.-]*\d)(?=[A-Za-z0-9_.-]*[A-Za-z])[A-Za-z0-9]{1,10}(?:[-_.][A-Za-z0-9]{1,12}){0,5}\b")
PROJCODE = re.compile(r"\b[A-Z]{2,5}(?:-[A-Z0-9]{2,12}){2,5}\b")

def ctx(text: str, s: int, e: int, w: int = 40) -> str:
    return re.sub(r"\s+", " ", text[max(0, s - w): e + w])

class Acc:
    def __init__(self):
        self.d = {}   # (type, value) -> [occ, files set, srcs counter, ctxs]

    def add(self, typ, val, src, fid, context):
        k = (typ, val)
        r = self.d.get(k)
        if r is None:
            r = self.d[k] = [0, set(), collections.Counter(), []]
        r[0] += 1
        r[1].add(fid)
        r[2][src] += 1
        if len(r[3]) < MAX_CTX and context not in r[3]:
            r[3].append(context[:120])

def scan_text(acc: Acc, text: str, src: str, fid: int, phone_needs_ctx: bool = True):
    if not text:
        return
    for m in URL.finditer(text):
        acc.add("url", m.group(0).rstrip(".,;"), src, fid, ctx(text, m.start(), m.end()))
    for m in EMAIL.finditer(text):
        acc.add("email", m.group(0).lower(), src, fid, ctx(text, m.start(), m.end()))
    for m in HOST.finditer(text):
        v = m.group(0).lower()
        if not SOFTWARE.fullmatch(v.split(".")[0]):
            acc.add("host", v, src, fid, ctx(text, m.start(), m.end()))
    for m in USERPATH.finditer(text):
        acc.add("username", m.group(1), src, fid, ctx(text, m.start(), m.end()))
    for m in DOMUSER.finditer(text):
        acc.add("username", m.group(0), src, fid, ctx(text, m.start(), m.end()))
    for m in PHONE.finditer(text):
        v = m.group(0).strip()
        digits = re.sub(r"\D", "", v)
        if not 7 <= len(digits) <= 15 or DATE.match(v):
            continue
        pre = text[max(0, m.start() - 25): m.start()]
        has = bool(PHONE_CTX.search(pre)) or v.startswith(("+", "("))
        if phone_needs_ctx and not has:
            continue
        acc.add("phone" if has else "phone?", v, src, fid, ctx(text, m.start(), m.end()))
    for m in ADDRESS.finditer(text):
        acc.add("address", m.group(0).strip(), src, fid, ctx(text, m.start(), m.end()))
    for m in PARTLABEL.finditer(text):
        v = m.group(1).strip("./-")
        if re.search(r"\d", v) and not engineering(v):
            acc.add("partno:label", v, src, fid, ctx(text, m.start(), m.end()))
    for m in PROJCODE.finditer(text):
        v = m.group(0)
        if not engineering(v):
            acc.add("projcode", v, src, fid, ctx(text, m.start(), m.end()))
    for m in CODE.finditer(text):
        v = m.group(0)
        if len(v) < 6 or engineering(v) or re.fullmatch(r"[\d.\-_]+[A-Za-z]?", v):
            continue
        if re.fullmatch(r"v?\d+(\.\d+)+", v, re.I):       # versions
            continue
        acc.add("code", v, src, fid, ctx(text, m.start(), m.end()))
    for m in INVENTED.finditer(text):
        v = m.group(0)
        if len(v) >= 5 and not in_dict(v) and not engineering(v):
            acc.add("invented", v, src, fid, ctx(text, m.start(), m.end()))
    for m in DOTTED.finditer(text):
        v = m.group(0)
        parts = v.split(".")
        if parts[-1] in TLDS.split("|"):
            continue
        if sum(not in_dict(p) for p in parts) >= 2:
            acc.add("invented.dotted", v, src, fid, ctx(text, m.start(), m.end()))

# ---------------------------------------------------------------- per-format metadata
def printable(b: bytes) -> str:
    # ASCII strings and UTF-16LE strings, joined by newlines
    a = re.findall(rb"[\x20-\x7e]{5,}", b)
    u = re.findall(rb"(?:[\x20-\x7e]\x00){5,}", b)
    return "\n".join([x.decode("ascii") for x in a] + [x.decode("utf-16le", "ignore") for x in u])

def meta_pdf(path):
    import fitz
    out_meta, pages = [], []
    try:
        doc = fitz.open(path)
    except Exception:
        return "", []
    try:
        md = doc.metadata or {}
        out_meta.append("\n".join(f"{k}: {v}" for k, v in md.items() if v))
        try:
            xmp = doc.get_xml_metadata() or ""
            out_meta.append(re.sub(r"<[^>]+>", " ", xmp))
        except Exception:
            pass
        for i, page in enumerate(doc):
            if i >= MAX_PDF_PAGES:
                break
            try:
                pages.append(page.get_text("text"))
            except Exception:
                pass
    finally:
        doc.close()
    return "\n".join(out_meta), pages

def meta_ole(path):
    import olefile
    try:
        ole = olefile.OleFileIO(path)
    except Exception:
        return ""
    try:
        m = ole.get_metadata()
        fields = []
        for a in ("author", "last_saved_by", "company", "manager", "title", "subject", "keywords",
                  "comments", "category", "template"):
            v = getattr(m, a, None)
            if v:
                fields.append(f"{a}: {v.decode('latin-1', 'ignore') if isinstance(v, bytes) else v}")
        return "\n".join(fields)
    finally:
        ole.close()

def meta_zipxml(path):
    out = []
    try:
        with zipfile.ZipFile(path) as z:
            for n in z.namelist():
                ln = n.lower()
                if ln in ("document.xml", "3d/3dmodel.model", "docprops/core.xml", "docprops/app.xml", "metadata/model_settings.config") \
                        or ln.endswith("core.xml"):
                    data = z.read(n)[:HEAD * 4].decode("utf-8", "ignore")
                    # FCStd: keep header properties only (before ObjectData)
                    data = data.split("<ObjectData")[0]
                    out.append(re.sub(r"<[^>]+?(?:value|name)=\"([^\"]*)\"[^>]*>", r" \1 ", data))
    except Exception:
        pass
    return "\n".join(out)

TEXT_HEAD_EXT = {"step", "stp", "igs", "iges", "dxf", "svg", "obj", "wrl", "vrml", "x_t", "sat", "txt", "md",
                 "csv", "json", "xml", "scad", "gcode", "nc", "ini", "cfg", "html", "htm", "kicad_pcb", "sch"}

def process(item):
    fid, path, rel = item
    acc = Acc()
    # 1. path components (relative path, split into segments and words)
    scan_text(acc, rel.replace("/", " / ").replace("_", " _ "), "path", fid, phone_needs_ctx=True)
    for seg in rel.split("/"):
        stem = seg.rsplit(".", 1)[0]
        if CODE.fullmatch(stem) and re.search(r"\d", stem) and not engineering(stem) and len(stem) >= 6:
            acc.add("partno:filename", stem, "path", fid, rel[-120:])
    ext = rel.rsplit(".", 1)[-1].lower() if "." in rel else ""
    try:
        if ext == "pdf":
            md, pages = meta_pdf(path)
            scan_text(acc, md, "pdfmeta", fid)
            for p in pages:
                scan_text(acc, p, "pdftext", fid)
        else:
            sz = os.path.getsize(path)
            with open(path, "rb") as f:
                head = f.read(HEAD)
                tail = b""
                if sz > 2 * HEAD:
                    f.seek(sz - HEAD)
                    tail = f.read(HEAD)
            if head[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
                scan_text(acc, meta_ole(path), "olemeta", fid)
            elif head[:2] == b"PK" and ext in ("fcstd", "3mf", "docx", "xlsx", "pptx", "f3d"):
                scan_text(acc, meta_zipxml(path), "zipmeta", fid)
            if ext in TEXT_HEAD_EXT:
                txt = head.decode("utf-8", "ignore")
                if ext in ("step", "stp"):
                    txt = txt.split("ENDSEC;")[0]                       # header section only
                    src = "stephdr"
                elif ext in ("igs", "iges"):
                    txt = "\n".join(l[:72] for l in txt.splitlines() if l[72:73] in ("S", "G"))
                    src = "igeshdr"
                else:
                    src = "texthead"
                scan_text(acc, txt, src, fid)
            else:
                # binaries: only high-precision types in raw strings
                s = printable(head + tail)
                for m in USERPATH.finditer(s):
                    acc.add("username", m.group(1), "rawstr", fid, ctx(s, m.start(), m.end()))
                for m in DOMUSER.finditer(s):
                    acc.add("username", m.group(0), "rawstr", fid, ctx(s, m.start(), m.end()))
                for m in EMAIL.finditer(s):
                    acc.add("email", m.group(0).lower(), "rawstr", fid, ctx(s, m.start(), m.end()))
                for m in URL.finditer(s):
                    acc.add("url", m.group(0), "rawstr", fid, ctx(s, m.start(), m.end()))
    except Exception as e:  # never die on one file
        acc.add("_error", type(e).__name__, ext, fid, rel[-100:])
    return {k: (v[0], list(v[1]), dict(v[2]), v[3]) for k, v in acc.d.items()}

def init_worker():
    global DICT
    DICT = load_dict()

# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("out")
    ap.add_argument("--registry")
    ap.add_argument("--procs", type=int, default=8)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--min-files", type=int, default=1)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)

    items = []
    for root, dirs, files in os.walk(a.input):
        dirs.sort()
        for fn in sorted(files):
            p = os.path.join(root, fn)
            items.append((len(items), p, os.path.relpath(p, a.input)))
    if a.limit:
        step = max(1, len(items) // a.limit)
        items = items[::step][: a.limit]
    print(f"files: {len(items)}", flush=True)

    reg = set()
    if a.registry:
        for ident in json.load(open(a.registry))["identities"]:
            reg.add(ident["value"].lower())

    total = {}
    with mp.Pool(a.procs, initializer=init_worker) as pool:
        for n, res in enumerate(pool.imap_unordered(process, items, chunksize=16), 1):
            for k, (occ, fids, srcs, cx) in res.items():
                r = total.get(k)
                if r is None:
                    r = total[k] = [0, set(), collections.Counter(), []]
                r[0] += occ
                r[1].update(fids)
                r[2].update(srcs)
                for c in cx:
                    if len(r[3]) < MAX_CTX and c not in r[3]:
                        r[3].append(c)
            if n % 5000 == 0:
                print(f"{n}/{len(items)} candidates={len(total)}", flush=True)

    # cross-type evidence: a code that also appears as a file-name stem is strong
    fname_codes = {v.lower() for (t, v) in total if t == "partno:filename"}
    rows = []
    for (t, v), (occ, fids, srcs, cx) in total.items():
        if len(fids) < a.min_files:
            continue
        vl = v.lower()
        inreg = "full" if vl in reg else ("part" if any(w in reg for w in re.split(r"[\s._/@-]+", vl) if len(w) > 3) else "")
        rows.append((t, v, occ, len(fids), "|".join(f"{s}:{c}" for s, c in srcs.most_common()),
                     inreg, "Y" if vl in fname_codes else "", " ¦ ".join(cx)))
    rows.sort(key=lambda r: (r[0], -r[3], -r[2]))
    with open(os.path.join(a.out, "candidates.tsv"), "w") as f:
        f.write("type\tvalue\tocc\tfiles\tsources\tin_registry\talso_filename\tcontexts\n")
        for r in rows:
            f.write("\t".join(str(x).replace("\t", " ").replace("\n", " ") for x in r) + "\n")
    # summary (no values)
    summ = collections.defaultdict(lambda: [0, 0, 0, 0])
    for r in rows:
        s = summ[r[0]]
        s[0] += 1
        s[1] += r[2]
        s[2] += (r[5] == "")
        s[3] += (r[5] == "" and r[3] >= 2)
    with open(os.path.join(a.out, "summary.txt"), "w") as f:
        f.write("type\tdistinct\tocc\tnot_in_registry\tnot_in_reg_and_files>=2\n")
        for t in sorted(summ):
            f.write(f"{t}\t" + "\t".join(map(str, summ[t])) + "\n")
    print(open(os.path.join(a.out, "summary.txt")).read())

if __name__ == "__main__":
    main()
