"""Local evaluator for the server's three PDF categories (agent B).

    python -m deid.pdfeval INPUT OUTPUT RESULTS_JSON REGISTRY [-n 800] [-j 8] [--fail FAIL.tsv]

(a) scoped removal: every registry identity occurrence in PDF page text is
    gone, and ONLY identity text changed (word-level diff of input vs output
    page text; any changed word that does not overlap an identity is a scope
    violation; dropped pages/text also count);
(b) consistency: each identity's replacement is the same everywhere, in PDF
    page text and in non-PDF files (same-length byte rewrites: bytes at the
    original offsets), and equals the registry pseudonym;
(c) distinct: no replacement string is shared by two identities, and no
    pseudonym equals another identity's original.

Prints rates (no identity strings). The failure list (contains originals:
keep it private, never commit) goes to --fail.
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import random
import re
import sys
from collections import Counter, defaultdict
from multiprocessing import Pool

G: dict = {}
_WORD = re.compile(r"\S+")
_PUNCT = re.compile(r"[^a-z0-9]+")
_TEXTY = {"txt", "md", "csv", "xml", "json", "html", "htm", "stp", "step", "igs", "iges", "dxf", "obj", "mtl", "scad",
          "urdf", "sdf", "yaml", "yml", "ini", "cfg", "svg", "tex", "log"}


def _init(reg, secret):
    from deid.rewrite import load_mappers

    _, G["m"] = load_mappers(reg, secret)  # content (global-scope) identities: what content rewriting applies
    from deid.detect import Explainer

    G["ex"] = Explainer(pseudonyms=G["m"].entries.values())
    G["ptok"] = {t for p in G["m"].entries.values() for t in re.findall(r"[a-z0-9]+", p.lower())}


def _ext(p):
    b = p.rsplit("/", 1)[-1]
    return b.rsplit(".", 1)[-1].lower() if "." in b else ""


def _pages(path, max_pages=8):
    import fitz

    out = []
    with fitz.open(path) as d:
        for i, pg in enumerate(d):
            if i >= max_pages:
                break
            out.append(pg.get_text("text").encode("ascii", "ignore").decode())
    return out


_LABEL = re.compile(r"(?i:\b(?:drawn|checked|approved|designed|designer|author|engineer|drafter|created|prepared|"
                    r"reviewed|owner|contact)\b(?:\s+by)?\s*[:.]?\s*)([A-Z][a-z]{1,20}(?:[ ]+[A-Z]\.?(?![a-z])){0,1}"
                    r"(?:[ ]+[A-Z][a-z]{1,20}){0,2})")
_ORG = re.compile(r"\b([A-Z][\w&.-]{1,30}(?:[ ]+[A-Z][\w&.-]{1,30}){0,4})[ ,]+(Inc|Ltd|LLC|GmbH|AG|Corp|Corporation|"
                  r"S\.A\.|B\.V\.|S\.r\.l\.|SRL|Pty|Limited|Co\., Ltd)\b\.?")
_UNI = re.compile(r"\b((?:University|Institute|College|Universit[a-z]+|Laboratory)[ ]+of[ ]+[A-Z][a-z]+(?:[ ]+[A-Z][a-z]+){0,3}"
                  r"|[A-Z][a-z]+(?:[ ]+[A-Z][a-z]+){0,3}[ ]+(?:University|Institute|Universit[a-z]+))\b")
_COPY = re.compile(r"(?:\u00a9|\(c\)|(?i:copyright))\s*(?:\d{4}[-, ]*)*\s*([A-Z][\w&.-]{1,30}(?:[ ]+[A-Z][\w&.-]{1,30}){0,4})")


def unknown_candidates(text, ex):
    """Identity-shaped strings in output page text not explained by pseudonyms/generic words."""
    from deid.detect import scan_patterns

    out = []
    for rx, kind in ((_LABEL, "label-name"), (_ORG, "company"), (_UNI, "institution"), (_COPY, "copyright")):
        for mt in rx.finditer(text):
            v = mt.group(0) if kind in ("company", "institution") else mt.group(1)
            if not ex.explained(v):
                out.append((kind, v.strip()))
    c, samples = Counter(), {}
    scan_patterns(text.encode("ascii", "ignore"), ex, c, samples)
    for kind, vals in samples.items():
        out.extend((kind, v) for v in vals)
    return out


def _norm(s):
    return _PUNCT.sub("", s.lower())


def eval_pdf(src, dst, rel):
    m = G["m"]
    r = Counter()
    fails, obs = [], []  # obs: (key, observed replacement)
    try:
        a = _pages(src)
    except Exception:
        return r, fails, obs
    try:
        b = _pages(dst)
    except Exception:
        b = []
    file_bad = False
    for pi, ta in enumerate(a):
        tb_raw = b[pi] if pi < len(b) else ""
        for kind, v in unknown_candidates(tb_raw, G["ex"]):
            r["unknown"] += 1
            file_bad = True
            fails.append(("unknown-" + kind, rel, pi + 1, v[:80], ""))
        ta, tb = ta.lower(), tb_raw.lower()
        wa = [(x.start(), x.end(), x.group()) for x in _WORD.finditer(ta)]
        wb = [x.group() for x in _WORD.finditer(tb)]
        if not wa:
            continue
        r["pages"] += 1
        # identity spans -> word indices
        idw = {}  # word index -> key
        occ = []  # (key, first word, last word)
        for s, e, key in m.find(ta.encode("ascii", "ignore")):
            ws = [i for i, (x0, x1, _) in enumerate(wa) if x0 < e and x1 > s]
            if ws:
                occ.append((key, ws[0], ws[-1]))
                for i in ws:
                    idw[i] = key
        sm = difflib.SequenceMatcher(None, [w for _, _, w in wa], wb, autojunk=False)
        op_of = {}
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            for i in range(i1, i2):
                op_of[i] = (tag, i1, i2, j1, j2)
            if tag == "equal":
                continue
            r["changed_words"] += max(i2 - i1, j2 - j1)
            ptok = G.get("ptok", set())
            ins_ok = all(t in ptok for w in wb[j1:j2] for t in re.findall(r"[a-z0-9]+", w))
            if i1 == i2:  # pure insertion: in scope if it is pseudonym text or next to an identity
                if not ins_ok and (i1 - 1) not in idw and i1 not in idw:
                    r["scope_viol"] += 1
                    fails.append(("scope-insert", rel, pi + 1, "", " ".join(wb[j1:j2])[:80]))
                continue
            out_of_scope = [i for i in range(i1, i2) if i not in idw]
            if out_of_scope:
                r["scope_viol"] += 1
                fails.append(("scope-change", rel, pi + 1, " ".join(wa[i][2] for i in out_of_scope)[:80],
                              " ".join(wb[j1:j2])[:80]))
        if not tb.strip():
            r["page_text_lost"] += 1
            fails.append(("page-text-lost", rel, pi + 1, "", ""))
        # replacement text may be re-flowed anywhere on the page: compare counts per page, not positions
        nb = _norm(tb)
        need = Counter(k for k, _, _ in occ)
        for key, n_in in need.items():
            r["occ"] += n_in
            n_out = len(re.findall(r"(?<![a-z0-9])" + re.escape(key) + r"(?![a-z0-9])", tb))
            left = min(n_in, n_out)
            r["leak"] += left
            r["removed"] += n_in - left
            if left:
                fails.append(("leak", rel, pi + 1, key, f"{left}/{n_in} left"))
            pseudo = _norm(m.entries[key])
            n_ps = nb.count(pseudo) if pseudo else 0
            good = min(n_in - left, n_ps)
            r["consistent"] += good
            if good:
                obs.append((key, pseudo))
            if good < n_in - left:
                fails.append(("no-pseudonym", rel, pi + 1, key, f"removed {n_in - left}, pseudonym found {n_ps}"))
    if len(b) < len(a):
        r["pages_lost"] += len(a) - len(b)
    file_bad = file_bad or any(f[0] in ("leak", "scope-change", "scope-insert", "page-text-lost") for f in fails)
    r["file_clean"] += int(not file_bad)
    r["file_consistent"] += int(not any(f[0] == "no-pseudonym" for f in fails))
    return r, fails, obs


def eval_bytes(src, dst, rel):
    """Non-PDF same-length rewrites: replacement = output bytes at the original offsets."""
    m = G["m"]
    obs = []
    try:
        if os.path.getsize(src) > 5_000_000 or os.path.getsize(src) != os.path.getsize(dst):
            return obs
        a, b = open(src, "rb").read(), open(dst, "rb").read()
    except OSError:
        return obs
    for s, e, key in m.find(a):
        got, want = _norm(b[s:e].decode("latin-1")), _norm(m.entries[key])
        if len(got) == len(want) and got != _norm(key):  # a same-layout replacement was written here
            obs.append((key, got))
    return obs


def work(args):
    in_root, out_root, rel, new_rel = args
    src, dst = os.path.join(in_root, rel), os.path.join(out_root, new_rel)
    if not os.path.exists(dst):
        return "missing", Counter(), [("missing-output", new_rel, 0, "", "")], []
    if _ext(rel) == "pdf":
        r, f, o = eval_pdf(src, dst, new_rel)
        return "pdf", r, f, o
    return "other", Counter(), [], eval_bytes(src, dst, new_rel)


def main(argv=None):
    from deid.checker import held_out

    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("output")
    ap.add_argument("results")
    ap.add_argument("registry")
    ap.add_argument("-n", type=int, default=800, help="held-out PDFs to evaluate")
    ap.add_argument("--other", type=int, default=3000, help="held-out non-PDF text files for consistency")
    ap.add_argument("-j", type=int, default=8)
    ap.add_argument("--fail", default="pdfeval-failures.tsv")
    a = ap.parse_args(argv)
    secret = os.environ.get("DEID_SECRET", "machina-deid-default-secret").encode()
    mapping = {r: nr for r, nr, _ in json.loads(open(a.results).read())}
    ho = [r for r in mapping if held_out(r)]
    rnd = random.Random(1234)
    pdfs = [r for r in ho if _ext(r) == "pdf"]
    others = [r for r in ho if _ext(r) in _TEXTY]
    rnd.shuffle(pdfs)
    rnd.shuffle(others)
    jobs = [(a.input, a.output, r, mapping[r]) for r in pdfs[:a.n] + others[:a.other]]
    tot, fails = Counter(), []
    seen = defaultdict(Counter)  # key -> replacement counts
    with Pool(a.j, initializer=_init, initargs=(a.registry, secret)) as pool:
        for kind, r, f, o in pool.imap_unordered(work, jobs, chunksize=4):
            tot.update(r)
            tot[kind + "_files"] += 1
            fails.extend(f)
            for k, v in o:
                if v:
                    seen[k][v] += 1
    _init(a.registry, secret)
    m = G["m"]
    # (b) consistency per identity: one replacement everywhere, equal to the registry pseudonym
    inc_ids = [k for k, c in seen.items() if len(c) > 1 or _norm(m.entries[k]) not in c]
    for k in inc_ids[:2000]:
        fails.append(("identity-inconsistent", "", 0, k, json.dumps(dict(seen[k].most_common(4)))))
    # (c) distinct: replacement shared by different identities; pseudonym equal to another original
    by_rep = defaultdict(set)
    for k, c in seen.items():
        for v in c:
            by_rep[v].add(k)
    shared = {v: ks for v, ks in by_rep.items() if len(ks) > 1}
    for v, ks in list(shared.items())[:2000]:
        fails.append(("collision", "", 0, " | ".join(sorted(ks))[:200], v))
    originals = {_norm(k) for k in m.entries}
    clash = [k for k, p in m.entries.items() if _norm(p) in originals]
    for k in clash[:500]:
        fails.append(("pseudonym-is-original", "", 0, k, m.entries[k]))
    occ = tot["occ"] or 1
    print(f"PDFs evaluated: {tot['pdf_files']} (pages {tot['pages']}, pages lost {tot['pages_lost']}, "
          f"page text lost {tot['page_text_lost']}); non-PDF files: {tot['other_files']}; missing {tot['missing_files']}")
    print(f"(a) scoped removal: occurrences={tot['occ']} removed={tot['removed'] / occ:.3f} leaks={tot['leak']} "
          f"out-of-scope edits={tot['scope_viol']} (changed words {tot['changed_words']})")
    print(f"(b) consistency: occurrences consistent={tot['consistent'] / occ:.3f}; identities seen={len(seen)} "
          f"inconsistent={len(inc_ids)}")
    print(f"(c) distinct: shared replacements={len(shared)} pseudonym-equals-original={len(clash)}")
    nf = tot["pdf_files"] or 1
    print(f"per-file (server-like): clean (no leak/unknown/scope) {tot['file_clean'] / nf:.3f}  "
          f"consistent {tot['file_consistent'] / nf:.3f}  unknown identity candidates {tot['unknown']}")
    uk = Counter((f[0], f[3]) for f in fails if f[0].startswith("unknown-"))
    with open(a.fail.replace(".tsv", "") + "-unknown.tsv", "w") as fh:
        fh.write("count\tkind\tvalue\n")
        for (k, v), n in uk.most_common():
            fh.write(f"{n}\t{k[8:]}\t{v}\n")
    print("unknown candidates by kind:", Counter(k for k, _ in uk.elements()).most_common())
    print("failures by type:", Counter(f[0] for f in fails).most_common())
    with open(a.fail, "w") as fh:
        fh.write("type\tpath\tpage\toriginal\tobserved\n")
        for f in fails:
            fh.write("\t".join(str(x).replace("\t", " ").replace("\n", " ") for x in f) + "\n")
    print(f"failure list (private, contains originals): {a.fail}")


if __name__ == "__main__":
    main()
