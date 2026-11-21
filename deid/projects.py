"""Project-name harvester (owner: B).

Candidates:
  repo   - word n-grams (1..4) of each repository name (sources/<host>/<owner>__<repo>), split on separators and camelCase,
           kept when they occur >= 2 times in that repo's own text and in at most MAX_OTHER other repos (specificity).
  label  - values after "Project:", "Projekt:", "Proyecto:", "Projet:", "Project name:" and "<X>-Projekt" / "<X> Project".
Surface forms are emitted exactly as they appear in text (e.g. "Zarvo-Arm", "QX5D Vorlo"; synthetic).
Usage: python -m deid.projects INPUT_DIR OUT.tsv [-j 28]      OUT.tsv: kind<TAB>value  (private)
       OUT.tsv.stats: count<TAB>repos<TAB>source<TAB>value
"""
import os
import re
import sys
from collections import Counter, defaultdict
from multiprocessing import Pool

MAX_OTHER = 3
GENERIC = set("""hardware hw cad cam design designs designed files file models model step stp stl parts part project projects open
source opensource mechanical mechanics mech electronics electronic pcb board boards printer printers print printing printed 3d 2d cnc
machine machines robot robots robotic robotics large format small mini micro v1 v2 v3 v4 v5 master main repo repository src docs doc
documentation drawings drawing assembly assemblies kit build system systems tool tools tooling diy lab labs public release releases the
of and for a an with to in on by new old library lib libraries data test tests example examples demo template templates base core
solidworks freecad fusion fusion360 inventor onshape kicad eagle openscad sketchup creo catia nx parametric 2014 2015 2016 2017 2018
2019 2020 2021 2022 2023 2024 2025 2026 sw mm inch metric frame case enclosure mount holder stand box arm hand leg joint motor
gear gears wheel wheels shaft plate bracket""".split())
LABEL = re.compile(r"(?:\b(?i:project(?:\s*name)?|projekt(?:name)?|proyecto|projet|projecte)\s*[:=]\s*)"
                   r"([A-Za-z0-9][A-Za-z0-9_\-\.\+äöüÄÖÜß]*(?:[ ][A-Z0-9][A-Za-z0-9_\-\.\+äöüÄÖÜß]*){0,3})")
LABEL2 = re.compile(r"\b([A-Z][A-Za-z0-9äöüß]{3,}(?:[ \-][A-Z][A-Za-z0-9äöüß]+){0,2})[ \-](?:Projekt|Project|Proyecto)\b(?!\s*(?i:name|manager|team))")
LSTOP = re.compile(r"(?i)^(?:unnamed|untitled|none|n/?a|tbd|name|title|number|no|date|description|manager|team|leader|default|"
                   r"the|this|our|your|my|a|an|new|test|example|demo|final|work|school|student|course|group|ein|eine|das|der|die|el|la)$")
TEXT_EXT = {"txt", "md", "csv", "tsv", "xml", "html", "htm", "json", "step", "stp", "sch", "kicad_sch", "kicad_pcb", "ini", "cfg",
            "yaml", "yml", "rst", "scad", "iges", "igs", "dxf", "obj"}
WORDS = set()
TOK = re.compile(r"[A-Za-z0-9]+")
CAMEL = re.compile(r"[A-Z0-9]+(?=[A-Z][a-z])|[A-Z]?[a-z]+[0-9]*|[A-Z0-9]+|[0-9]+")


def _load_words():
    global WORDS
    try:
        WORDS = {w.strip().lower() for w in open("/usr/share/dict/words", encoding="utf-8", errors="ignore") if w.strip()}
    except OSError:
        WORDS = set()


def split_name(name):
    out = []
    for part in re.split(r"[^A-Za-z0-9]+", name):
        out += [p.lower() for p in CAMEL.findall(part)] if part else []
    return out


def repo_candidates(repo):
    toks = split_name(repo)
    cands = set()
    for n in range(1, 5):
        for i in range(len(toks) - n + 1):
            g = toks[i:i + n]
            if all(t in GENERIC for t in g):
                continue
            if g[0] in GENERIC and n > 1 and g[0] in ("the", "of", "and", "for", "a", "an"):
                continue
            if n == 1 and (len(g[0]) < 3 or g[0] in WORDS or g[0].isdigit()):
                continue
            cands.add(" ".join(g))
    return cands


def repo_of(path, root):
    rel = os.path.relpath(path, root).split(os.sep)
    if len(rel) >= 3 and rel[0] == "sources":
        return "/".join(rel[:3]), rel[2]
    return "/".join(rel[:2]), rel[1] if len(rel) > 1 else rel[0]


def _texts(path):
    ext = path.rsplit(".", 1)[-1].lower() if "." in os.path.basename(path) else ""
    try:
        if ext == "pdf":
            import fitz
            with fitz.open(path) as d:
                for i in range(min(len(d), 40)):
                    yield d[i].get_text("text")
        elif ext in TEXT_EXT:
            with open(path, "rb") as fh:
                yield fh.read(1_000_000).decode("utf-8", "ignore")
    except Exception:
        return


def ngrams_with_spans(t):
    """word pieces (camel-split inside tokens) with offsets -> yields (normalized ngram, surface) for n=1..4"""
    pieces = []
    for m in TOK.finditer(t):
        tok = m.group()
        for c in CAMEL.finditer(tok):
            pieces.append((c.group().lower(), m.start() + c.start(), m.start() + c.end(), m.start(), m.end()))
    for i in range(len(pieces)):
        for n in range(1, 5):
            if i + n > len(pieces):
                break
            seg = pieces[i:i + n]
            if any(seg[k + 1][1] - seg[k][2] > 1 for k in range(n - 1)):
                break  # only directly adjacent pieces (one separator char at most)
            yield " ".join(p[0] for p in seg), seg[0][1], seg[-1][2], seg[0][3], seg[-1][4]


CANDS = set()


def _init(cands):
    global CANDS
    _load_words()
    CANDS = cands


def scan_file(args):
    path, root = args
    cands = CANDS
    key, repo = repo_of(path, root)
    hits = Counter()
    surf = defaultdict(Counter)
    labels = Counter()
    texts = list(_texts(path))
    texts.append(os.path.relpath(path, root).replace(os.sep, " / "))
    for t in texts:
        for g, s, e, ts, te in ngrams_with_spans(t):
            if g in cands:
                hits[g] += 1
                # surface: whole token if the n-gram covers it entirely, else the exact span
                surf[g][t[s:e]] += 1
        for rx in (LABEL, LABEL2):
            for m in rx.finditer(t):
                v = m.group(1).strip(" .-_")
                if 3 <= len(v) <= 40 and not LSTOP.match(v.split()[0]) and re.search(r"[A-Za-z]", v):
                    labels[v] += 1
    return key, hits, surf, labels


def main(argv):
    root, out = argv[0], argv[1]
    j = int(argv[argv.index("-j") + 1]) if "-j" in argv else 28
    _load_words()
    paths = [os.path.join(d, f) for d, _, fs in os.walk(root) for f in fs]
    repo_c = {}
    for p in paths:
        key, repo = repo_of(p, root)
        if key not in repo_c:
            name = repo.split("__", 1)[1] if "__" in repo else repo
            repo_c[key] = repo_candidates(name)
    allc = set().union(*repo_c.values()) if repo_c else set()
    own = defaultdict(Counter)      # repo -> cand -> count
    where = defaultdict(set)        # cand -> repos where it occurs
    surf = defaultdict(Counter)
    labels = defaultdict(Counter)   # value -> repo -> count
    with Pool(j, initializer=_init, initargs=(allc,)) as pool:
        for key, hits, s, lab in pool.imap_unordered(scan_file, ((p, root) for p in paths), chunksize=16):
            for g, n in hits.items():
                where[g].add(key)
                if g in repo_c.get(key, ()):
                    own[key][g] += n
            for g, c in s.items():
                surf[g].update(c)
            for v, n in lab.items():
                labels[v][key] += n
    keep = {}
    for key, c in own.items():
        for g, n in c.items():
            if n >= 2 and len(where[g] - {key}) <= MAX_OTHER:
                for sv, sn in surf[g].most_common(6):
                    if sn >= 1 and re.search(r"[A-Za-z]", sv):
                        keep.setdefault(sv, (n, len(where[g]), "repo"))
    for v, reps in labels.items():
        if len(reps) <= MAX_OTHER + 1:
            keep.setdefault(v, (sum(reps.values()), len(reps), "label"))
    with open(out, "w") as fh, open(out + ".stats", "w") as fs:
        for v, (n, r, src) in sorted(keep.items(), key=lambda kv: -kv[1][0]):
            fh.write(f"project\t{v}\n")
            fs.write(f"{n}\t{r}\t{src}\t{v}\n")
    print(f"files {len(paths)} repos {len(repo_c)} repo-candidates {len(allc)} kept {len(keep)}")




# ---- selection: stats -> clean project list ---------------------------------------------------------------------
def _codeish(v):
    return bool(re.search(r"[a-z][A-Z]|_|[A-Za-z]\d|\d[A-Za-z]|\+\+", v))


def keep_value(v, src):
    toks = split_name(v)
    if not toks or re.fullmatch(r"[0-9a-f]{6,}", v.lower()) or len(v) < 3:
        return False
    nondict = [t for t in toks if t not in WORDS and t not in GENERIC and not t.isdigit() and not re.fullmatch(r"v\d+", t)]
    words = re.findall(r"[A-Za-z][A-Za-z0-9]*", v)
    if src == "label":
        return bool(nondict) or _codeish(v)
    if len(toks) == 1:
        return bool(nondict) or _codeish(v)
    if nondict or _codeish(v):
        return True
    # dictionary-only phrase: must look like a name (Title Case / ALL CAPS words), <= 3 words
    return len(words) <= 3 and all(w[0].isupper() for w in words)


def select(stats, out):
    _load_words()
    n = 0
    with open(out, "w") as fh:
        for l in open(stats, encoding="utf-8", errors="ignore"):
            try:
                cnt, reps, src, v = l.rstrip("\n").split("\t")
            except ValueError:
                continue
            if keep_value(v, src):
                fh.write(f"project\t{v}\n")
                n += 1
    return n


if __name__ == "__main__" and sys.argv[1:2] == ["select"]:
    print("selected", select(sys.argv[2], sys.argv[3]))
    sys.exit(0)


if __name__ == "__main__":
    main(sys.argv[1:])
