"""Inline (page-level) identity detection for DEID_INLINE_NER=1 (owner: B).

Pre-pass, run before the build (cached per unique page-text hash):
    python -m deid.inline build INPUT_DIR OUT.tsv [-j 28] [--ner /data/ner/work/preds.jsonl] [--cache DIR]
  -> OUT.tsv  kind<TAB>value   every person/company/address/email/phone span found by the page rules (and, optionally,
              GLiNER predictions from C's cache), de-duplicated and sorted.
Build-time hook (deterministic: values are added in sorted order before workers fork, so one identity = one pseudonym):
    from deid.inline import extend; extend(allm, content)      # reads $DEID_INLINE_TSV (default /data/registry/inline.tsv)

Page rules (no corpus-frequency threshold; over-redaction is cheap, misses are not):
  author lists   "Taylor, Moore, and Armstrong", "A and B", "X et al.", "Smith, J.", "J. Smith"
  role fields    DRAWN/CHECKED/APPROVED/Designed by/... values and initials (deid.persons rules)
  name + date    "<Name|INITIALS> dd/mm/yyyy" on a page that carries role labels (title blocks printed value-first)
  sign-off       "Prepared by|Signed|Signature|Author(s)|Contact|Responsible: <Name>"
"""
import hashlib
import json
import os
import re
import sys
from collections import Counter
from multiprocessing import Pool

from deid import persons as P

_COMMON = None


def common(w):
    """True for ordinary (lower-case) dictionary words; proper names (Taylor, Moore) are not common."""
    global _COMMON
    if _COMMON is None:
        try:
            _COMMON = {x.strip() for x in open("/usr/share/dict/words", encoding="utf-8", errors="ignore") if x.strip().islower()}
        except OSError:
            _COMMON = set()
        _COMMON |= {"the", "and", "of", "for", "with", "notes", "table", "contents", "figure", "page", "sheet", "part"}
    w = w.lower()
    return w in _COMMON or (w.endswith("s") and w[:-1] in _COMMON) or (w.endswith("es") and w[:-2] in _COMMON)


CAP = r"[A-Z][a-zà-ÿ'\-]{1,20}"
CONJ = r"(?:and|und|y|et|e|&)"
AUTHORS = re.compile(r"(?<![A-Za-z])(" + CAP + r"(?:,\s" + CAP + r"){1,6},?\s" + CONJ + r"\s" + CAP + r"|" + CAP + r"\s" + CONJ + r"\s" + CAP + r")(?![A-Za-z])")
ETAL = re.compile(r"(?<![A-Za-z])(" + CAP + r")\set\sal\.?")
SURINIT = re.compile(r"(?<![A-Za-z])(" + CAP + r"),\s((?:[A-Z]\.\s?){1,3})(?=[\s,;]|$)")
INITSUR = re.compile(r"(?<![A-Za-z])((?:[A-Z]\.\s?){1,2}" + CAP + r")(?![A-Za-z])")
DATE = r"(?:\d{1,2}[./-]\d{1,2}[./-]\d{2,4}|\d{4}-\d{2}-\d{2}|\d{1,2}[ /-](?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*[ /-]\d{2,4})"
NAMEDATE = re.compile(r"(?<![A-Za-z])(" + CAP + r"(?:\s" + CAP + r")?|[A-Z]{2,4})\s" + DATE)
SIGN = re.compile(r"(?i:\b(?:prepared\s*by|signed|signature|authors?|contact|responsible|verantwortlich|bearbeiter|autor(?:es)?|elaborado\s*por)"
                  r")\s*[:.]?\s*(" + CAP + r"(?:\s" + CAP + r"){0,2})")
ROLECUE = re.compile(r"(?i)\b(?:drawn|checked|approved|designed|designer|engr|dibujado|gezeichnet|gepr[üu]ft|comprobado|dessin[ée])\b")
EMAIL = re.compile(r"[A-Za-z0-9._%+\-]{1,64}@[A-Za-z0-9.\-]{1,120}\.[A-Za-z]{2,10}")


NOTNAME = set("""january february march april may june july august september october november december jan feb mar apr jun jul aug sep
sept oct nov dec monday tuesday wednesday thursday friday saturday sunday australia austria belgium brazil canada china denmark
finland france germany india italy japan korea mexico netherlands norway poland spain sweden switzerland taiwan usa china england
gnd vbus vcc vdd vss nvm pla petg abs allen fecha druck datum zeichnung zeichnungsnummer gehause gehäuse kurbelwelle zylinder
zylinderkopf bohrung kleinmaterial schaltgerate aluminium masa proj elec mech fan linux github gitlab reprap matlab dupont taptite
trilobular ligo pcb pdf dmm triac bbb contacto vistas cortes estudiantes""".split())


def _person_ok(v):
    toks = re.findall(r"[A-Za-zà-ÿ'\-]+", v)
    if not toks or len(v) < 2 or any(t.lower() in NOTNAME for t in toks):
        return False
    if re.fullmatch(r"[A-Z]{2,4}", v):
        return v not in P.STOP and v not in P.JARGON and (len(v) <= 2 or not common(v))
    return not all(common(t) for t in toks) and not any(t.upper() in P.STOP and len(t) > 3 for t in toks)


def page_spans(t):
    """-> list of (kind, value) for one page / text block."""
    out = []
    flat = re.sub(r"\s+", " ", t)
    for m in AUTHORS.finditer(flat):
        names = [x for x in re.split(r",?\s" + CONJ + r"\s|,\s", m.group(1)) if x]
        if len(names) >= 2 and sum(not common(x) for x in names) >= max(2, len(names) - 1):
            out += [("person", x) for x in names if not common(x)]
    for m in ETAL.finditer(flat):
        out.append(("person", m.group(1)))
    for m in SURINIT.finditer(flat):
        if not common(m.group(1)):
            out.append(("person", m.group(1)))
            out.append(("person", f"{m.group(1)}, {m.group(2).strip()}"))
    for m in INITSUR.finditer(flat):
        sur = re.sub(r"^(?:[A-Z]\.\s?)+", "", m.group(1))
        if not common(sur):
            out.append(("person", m.group(1)))
    for src, v in P.scan_text(t):
        if _person_ok(v):
            out.append(("person", v))
    if ROLECUE.search(flat):
        for m in NAMEDATE.finditer(flat):
            v = m.group(1)
            if _person_ok(v):
                out.append(("person", v))
    for m in SIGN.finditer(flat):
        if _person_ok(m.group(1)):
            out.append(("person", m.group(1)))
    for m in EMAIL.finditer(flat):
        out.append(("email", m.group(0)))
    return out


def _texts(path):
    ext = path.rsplit(".", 1)[-1].lower() if "." in os.path.basename(path) else ""
    try:
        if ext == "pdf":
            import fitz
            with fitz.open(path) as d:
                for i in range(min(len(d), 400)):
                    yield d[i].get_text("text")
        elif ext in ("txt", "md", "csv", "tsv", "html", "htm", "xml", "dxf", "svg", "rst"):
            with open(path, "rb") as fh:
                yield fh.read(2_000_000).decode("utf-8", "ignore")
    except Exception:
        return


_CACHE = None


def scan_file(path):
    res = Counter()
    for t in _texts(path):
        if not t.strip():
            continue
        h = hashlib.sha1(t.encode("utf-8", "replace")).hexdigest()
        cp = os.path.join(_CACHE, h[:2], h) if _CACHE else None
        spans = None
        if cp and os.path.exists(cp):
            try:
                spans = [tuple(x) for x in json.load(open(cp))]
            except (ValueError, OSError):
                spans = None
        if spans is None:
            spans = page_spans(t)
            if cp:
                os.makedirs(os.path.dirname(cp), exist_ok=True)
                tmp = f"{cp}.{os.getpid()}"
                with open(tmp, "w") as fh:
                    json.dump(spans, fh)
                os.replace(tmp, cp)
        res.update(spans)
    return res


def _init(cache):
    global _CACHE
    _CACHE = cache
    common("x")


NER_KIND = {"person": "person", "organization": "company", "company": "company", "university or institute": "company",
            "street address": "address", "phone number": "phone", "email address": "email"}
NER_STOP = set("""name unknown author users user you your licensor licensee supplier designer customer manufacturer vendor empresa
proyecto project bom cnc assy unc asme ansi iso din acis solidworks freecad autodesk inventor open cascade creative commons
open hardware the builder part number""".split())


def ner_values(preds_path, min_score=0.45):
    vals = Counter()
    for l in open(preds_path):
        for lab, v, s, e, sc in json.loads(l)["ents"]:
            k = NER_KIND.get(lab)
            v = re.sub(r"\s+", " ", v).strip(" ,.;:()[]\"'")
            if not k or sc < min_score or len(v) < 3 or len(v) > 80 or not re.search(r"[A-Za-z]{2}", v):
                continue
            if v.lower() in NER_STOP or v.lower() in NOTNAME or all(common(t) for t in re.findall(r"[A-Za-z]+", v)):
                continue
            if k == "person" and not _person_ok(v):
                continue
            vals[(k, v)] += 1
    return vals


def build(root, out, j=28, ner=None, cache=None):
    paths = [os.path.join(d, f) for d, _, fs in os.walk(root) for f in fs]
    tot = Counter()
    with Pool(j, initializer=_init, initargs=(cache,)) as pool:
        for c in pool.imap_unordered(scan_file, paths, chunksize=16):
            tot.update(c)
    if ner:
        tot.update(ner_values(ner))
    vals = {}
    for (k, v), n in tot.items():
        vals.setdefault(v, k)
    with open(out, "w") as fh:
        for v in sorted(vals):
            fh.write(f"{vals[v]}\t{v}\n")
    print(f"files {len(paths)} inline values {len(vals)}")


def extend(allm, content, path=None):
    """Build-time hook: add inline detections to both mappers in sorted order (deterministic pseudonyms)."""
    path = path or os.environ.get("DEID_INLINE_TSV", "/data/registry/inline.tsv")
    if not os.path.exists(path):
        return 0
    n = 0
    for l in sorted(open(path, encoding="utf-8", errors="ignore")):
        p = l.rstrip("\n").split("\t")
        if len(p) != 2 or not p[1]:
            continue
        allm.add(p[1], p[0])
        content.add(p[1], p[0])
        n += 1
    return n


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[:1] == ["build"]:
        j = int(a[a.index("-j") + 1]) if "-j" in a else 28
        ner = a[a.index("--ner") + 1] if "--ner" in a else None
        cache = a[a.index("--cache") + 1] if "--cache" in a else None
        build(a[1], a[2], j, ner, cache)


# ---- expand: grow registry hits to the enclosing code token / legal suffix ---------------------------------------
#   python -m deid.inline expand REGISTRY INPUT_DIR OUT.tsv [-j 28]
_MAP = None
CODECH = re.compile(rb"[A-Za-z0-9_+\-/]")
SUFFIX = re.compile(rb"\s(?:GmbH|Inc\.?|Ltd\.?|LLC|AG|S\.A\.|B\.V\.|Co\.,?\s?Ltd\.?|Corp\.?|s\.r\.o\.|Oy|A/S|AB|SE|S\.r\.l\.|S\.L\.|Pty\.?\s?Ltd\.?|KG|GmbH\s&\sCo\.\sKG)(?![A-Za-z])")


def _grow(b, s, e):
    """Extend [s,e) over code characters; ',' and '.' only between digits/alnum."""
    def ok(i):
        if i < 0 or i >= len(b):
            return False
        c = b[i:i + 1]
        if CODECH.match(c):
            return True
        if c in (b",", b".") and 0 < i < len(b) - 1:
            return chr(b[i - 1]).isalnum() and chr(b[i + 1]).isdigit()
        return False
    while ok(s - 1):
        s -= 1
    while ok(e):
        e += 1
    while e > s and b[e - 1:e] in (b".", b",", b"/", b"-", b"_", b"+"):
        e -= 1
    while s < e and b[s:s + 1] in (b"/", b"-", b"_", b"+"):
        s += 1
    return s, e


def expand_file(path):
    out = set()
    for t in _texts(path):
        b = re.sub(r"\s+", " ", t).encode("utf-8", "replace")
        if len(b) < 4:
            continue
        for s, e, _ in _MAP.find(b, "ascii"):
            gs, ge = _grow(b, s, e)
            if (gs, ge) != (s, e) and ge - gs <= 40:
                v = b[gs:ge].decode("utf-8", "ignore")
                if re.search(r"\d", v) and re.search(r"[A-Za-z]", v) and v.isascii():
                    out.add(("part", v))
            m = SUFFIX.match(b, e)
            if m and b[s:s + 1].isupper():
                out.add(("company", b[s:m.end()].decode("utf-8", "ignore")))
    return out


def expand(reg, root, out, j=28):
    global _MAP
    from deid.rewrite import load_mappers
    _, _MAP = load_mappers(reg, b"machina-deid-default-secret")
    _MAP.find(b"warm up", "ascii")
    paths = [os.path.join(d, f) for d, _, fs in os.walk(root) for f in fs if f.lower().endswith((".pdf", ".txt", ".md", ".csv"))]
    vals = set()
    with Pool(j) as pool:
        for s in pool.imap_unordered(expand_file, paths, chunksize=16):
            vals |= s
    with open(out, "w") as fh:
        for k, v in sorted(vals, key=lambda x: x[1]):
            fh.write(f"{k}\t{v}\n")
    print(f"files {len(paths)} expanded values {len(vals)}")


if __name__ == "__main__" and sys.argv[1:2] == ["expand"]:
    a = sys.argv[1:]
    expand(a[1], a[2], a[3], int(a[a.index("-j") + 1]) if "-j" in a else 28)
