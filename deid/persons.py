"""Title-block person harvester (owner: B).

Values after drawing-role labels (DRAWN / CHECKED / APPROVED / DESIGNED / ENGR / BY / Designed by / Drawn by / Gezeichnet /
Geprüft / Konstrukteur / Bearb. / Dibujado / Diseñado / Comprobado / Aprobado / Dessiné / Vérifié / drawing by):
  initials   2-4 capitals (BJD, ERF, ZM)          - kept only when seen >= 2 times after a role label, or in a date-revision row
  names      "J.MOSKWA", "K. BUCKLAND", "E. Mancini", "Victor Leung", "David Amigó"
Usage: python -m deid.persons INPUT_DIR OUT.tsv [-j 28]   OUT.tsv: person<TAB>value ; OUT.tsv.stats: count<TAB>repos<TAB>value
"""
import os
import re
import sys
from collections import Counter, defaultdict
from multiprocessing import Pool

ROLE = (r"(?:DRAWN(?:\s*BY)?|DRN|DRWN|CHECKED(?:\s*BY)?|CHK'?D|CHKD|APPROVED(?:\s*BY)?|APPV'?D|APPD|APPR\.?|DESIGNED(?:\s*BY)?|DESIGNER|DSGN|"
        r"ENGR\.?|ENGINEER|CREATED\s*BY|AUTHOR|REVIEWED\s*BY|drawing\s*by|drawn\s*by|designed\s*by|Gezeichnet|Gepr[üu]ft|Konstrukteur|"
        r"Bearb\.?|Erstellt|Dibujado|Dise[ñn]ado|Comprobado|Aprobado|Dessin[ée]|V[ée]rifi[ée]|Approuv[ée]|Disegnato|Controllato)")
LAB = re.compile(r"(?i:\b" + ROLE + r")(?![A-Za-z])\s*[:.]?\s*(?:(?:\d{1,2}[./-]\d{1,2}[./-]\d{2,4}|\d{4}-\d{2}-\d{2})\s+)?"
                 r"((?:[A-Z]\.\s?){1,2}[A-Z][A-Za-z'\-]{2,}|[A-Z]\.[A-Z]{2,}[A-Za-z'\-]*|[A-Z][a-zà-ÿ]+(?:\s[A-Z][a-zà-ÿ'\-]+){1,4}|[A-Z]{2,4})\b")
REVROW = re.compile(r"\b((?:[A-Z]{2,4}\s){0,2}[A-Z]{2,4})\s+(?:\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}|\d{1,2}/[A-Z]{3}/\d{2,4}|\d{4}-\d{2}-\d{2})\b")
ROLEW = re.compile(r"(?i)^" + ROLE + r"$")
STOP = set("""NAME DATE SIGNATURE TITLE SCALE SHEET SIZE REV DWG NO QA MFG FINISH MATERIAL WEIGHT BY THE AND FOR OF TO A AN SEE NOTE NOTES
ALL NONE NA TBD DO NOT UNLESS ITEM QTY PART DESCRIPTION APPROVED CHECKED DRAWN DESIGNED ENGR ANGLE THIRD FIRST MM INCH DATE: REVISION
STATUS DRAFT RELEASED DEBURR BREAK SHARP EDGES TOLERANCES LINEAR ANGULAR SURFACE THIS USE ISO DIN ANSI ASME CAD PDF STEP DXF APP CHK
DRN DSGN ECO ECN PCB BOM SW SOLIDWORKS FROM WITH AS ON IN AT BE IS ARE YES OK DFT DATE""".split())


def scan_text(t):
    out = []
    t1 = re.sub(r"[ \t]+", " ", t)
    for m in LAB.finditer(t1):
        v = m.group(1).strip()
        toks = v.split()
        while toks and ROLEW.match(toks[0]):
            toks.pop(0)
        if not toks:
            continue
        toks = toks[:3]
        v = " ".join(toks)
        if len(toks) == 1 and re.fullmatch(r"[A-Z][a-zà-ÿ]+", v):
            continue
        if v.upper() in STOP or any(w.upper() in STOP for w in re.split(r"[\s.]+", v) if w):
            continue
        out.append(("ini" if re.fullmatch(r"[A-Z]{2,4}", v) else "name", v))
    for m in REVROW.finditer(t1):
        for ini in m.group(1).split():
            if ini not in STOP:
                out.append(("revini", ini))
    return out


def _texts(path):
    ext = path.rsplit(".", 1)[-1].lower() if "." in os.path.basename(path) else ""
    try:
        if ext == "pdf":
            import fitz
            with fitz.open(path) as d:
                for i in range(min(len(d), 40)):
                    yield d[i].get_text("text")
        elif ext in ("dxf", "txt", "csv", "md"):
            with open(path, "rb") as fh:
                yield fh.read(2_000_000).decode("utf-8", "ignore")
    except Exception:
        return


def repo_of(path, root):
    rel = os.path.relpath(path, root).split(os.sep)
    return "/".join(rel[:3]) if len(rel) >= 3 and rel[0] == "sources" else "/".join(rel[:2])


def scan_file(args):
    path, root = args
    c = Counter()
    for t in _texts(path):
        c.update(scan_text(t))
    return repo_of(path, root), c


def main(argv):
    root, out = argv[0], argv[1]
    j = int(argv[argv.index("-j") + 1]) if "-j" in argv else 28
    paths = [os.path.join(d, f) for d, _, fs in os.walk(root) for f in fs if f.lower().endswith((".pdf", ".dxf", ".txt", ".csv", ".md"))]
    cnt = Counter()
    reps = defaultdict(set)
    with Pool(j) as pool:
        for rk, c in pool.imap_unordered(scan_file, ((p, root) for p in paths), chunksize=8):
            for k, n in c.items():
                cnt[k] += n
                reps[k].add(rk)
    byval = defaultdict(Counter)
    for (src, v), n in cnt.items():
        byval[v][src] += n
    kept = 0
    with open(out, "w") as fh, open(out + ".stats", "w") as fs:
        for v, srcs in sorted(byval.items(), key=lambda kv: -sum(kv[1].values())):
            r = len(set().union(*(reps[(s, v)] for s in srcs)))
            n = sum(srcs.values())
            fs.write(f"{n}\t{r}\t{','.join(srcs)}\t{v}\n")
            if re.fullmatch(r"[A-Z]{2,4}", v):
                ok = srcs["ini"] + srcs["revini"] >= 2 and r <= 3
            else:
                ok = r <= 5
            if ok:
                fh.write(f"person\t{v}\n")
                kept += 1
    print(f"files {len(paths)} values {len(byval)} kept {kept}")




# ---- selection ---------------------------------------------------------------------------------------------------
JARGON = set("""XXX XX SUS APPV APPR CAM ABDC ATDC BTDC TDC BDC CERN NTS TYP REF REQD MAX MIN NOM DIA RAD THK THRU CBORE CSK SPF EQ
OD ID PCD CL CTR ASSY SUB DET VIEW SEC DWG CHG ECR ECO DCN PDM ERP MRP QC QA LTD INC LLC GMBH AG CO CORP SPA SRL BV NV""".split())


def select(inp, out):
    try:
        words = {w.strip().lower() for w in open("/usr/share/dict/words", encoding="utf-8", errors="ignore")}
    except OSError:
        words = set()
    n = 0
    with open(out, "w") as fh:
        for l in open(inp, encoding="utf-8"):
            k, v = l.rstrip("\n").split("\t", 1)
            if re.fullmatch(r"[A-Z]{2,4}", v):
                if v in JARGON or v in STOP or v.lower() in words:
                    continue
            else:
                toks = re.findall(r"[A-Za-zà-ÿ]+", v)
                if toks and all(t.lower() in words for t in toks) and not re.search(r"[A-Z]\.", v):
                    continue
            fh.write(l); n += 1
    return n


if __name__ == "__main__" and sys.argv[1:2] == ["select"]:
    print("selected", select(sys.argv[2], sys.argv[3]))
    sys.exit(0)


if __name__ == "__main__":
    main(sys.argv[1:])
