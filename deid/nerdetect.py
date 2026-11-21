"""Content-level GLiNER detector (agent C), for B's PDF text replacement.

    from deid import nerdetect
    nerdetect.prefetch(all_page_texts, workers=32)   # optional: fill the cache in parallel, once per build
    spans = nerdetect.detect(page_text)              # [(start, end, kind)], kind in KINDS

Speed:
  * results are cached per text LINE (whitespace-normalised, sha1) in sqlite ($DEID_NER_CACHE). Title blocks,
    notes and headers repeat across pages and files, so most lines are cache hits. The cache is pre-filled from
    the full-corpus NER run (tools/nercache_import.py), so a build over the same input runs no model at all.
  * lines without letters / shorter than 3 chars never reach the model; pages without text cost nothing.
  * cache misses: prefetch() packs unique lines (in page order, so neighbours stay real context) into
    ~CHUNK_WORDS chunks and runs a multiprocess pool (spawn, 1 torch thread per worker, int8 dynamic
    quantisation unless DEID_NER_INT8=0). GPU is used automatically if torch sees one (then 1 worker).
  * without gliner/torch installed, detect() still returns cached spans (run_missing is a no-op).

Spans crossing a line break are dropped (cache unit = line). filter=True applies the engineering / software /
standards / generic-word filters of tools/nerpass.keep plus the NER gate rules (tools/nergate.drop).
"""
from __future__ import annotations

import glob
import hashlib
import json
import os
import re
import sqlite3
import sys

MODEL_DIR = os.environ.get("DEID_NER_MODEL") or next(iter(sorted(glob.glob(
    "/data/ner/work/hf/models--urchade--gliner_multi_pii-v1/snapshots/*"))), "urchade/gliner_multi_pii-v1")
CACHE = os.environ.get("DEID_NER_CACHE", "/data/ner/cache.sqlite")
THRESH = 0.45          # inference threshold (cached spans are all >= this); detect(min_score=) can raise it
CHUNK_WORDS = 200
BATCH = 8

# GLiNER prompt label -> registry kind
LABELS = {
    "person": "person",
    "company": "company",
    "organization": "company",
    "university or institute": "company",
    "project name": "project",
    "product or part number": "part",
    "street address": "address",
    "phone number": "phone",
    "email address": "email",
    "website or domain": "domain",
    "username": "account",
}
KINDS = sorted(set(LABELS.values()))
# registry kind -> label used by tools/nerpass.keep
_KEEP_LABEL = {"company": "organization", "part": "partno", "domain": "website", "account": "username"}

_WS = re.compile(r"\s+")
_LETTER = re.compile(r"[A-Za-zÀ-ÿ]")


# ------------------------------------------------------------------ lines + cache
def _norm(line: str):
    """Whitespace-collapsed line and map norm index -> original index."""
    out, imap, sp = [], [], False
    for i, ch in enumerate(line):
        if ch.isspace():
            sp = bool(out)
            continue
        if sp:
            out.append(" ")
            imap.append(i - 1)
            sp = False
        out.append(ch)
        imap.append(i)
    return "".join(out), imap


def _useful(n: str) -> bool:
    return len(n) >= 3 and bool(_LETTER.search(n))


def key(n: str) -> str:
    return hashlib.sha1(n.encode("utf-8", "surrogatepass")).hexdigest()[:24]


_DB = {}


def _db():
    pid = os.getpid()
    if pid not in _DB:
        con = sqlite3.connect(CACHE, timeout=60)
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("CREATE TABLE IF NOT EXISTS ner (k TEXT PRIMARY KEY, v TEXT)")
        _DB.clear()
        _DB[pid] = con
    return _DB[pid]


def cache_get(keys):
    keys = list(set(keys))
    out = {}
    con = _db()
    for i in range(0, len(keys), 900):
        part = keys[i:i + 900]
        for k, v in con.execute(f"SELECT k, v FROM ner WHERE k IN ({','.join('?' * len(part))})", part):
            out[k] = json.loads(v)
    return out


def cache_put(items):
    """items: {key: [[s, e, kind, score], ...]} (spans on the normalised line)."""
    con = _db()
    con.executemany("INSERT OR REPLACE INTO ner VALUES (?, ?)", [(k, json.dumps(v)) for k, v in items.items()])
    con.commit()


# ------------------------------------------------------------------ model
_M = None


def _load():
    global _M
    if _M is None:
        import torch
        from gliner import GLiNER
        m = GLiNER.from_pretrained(MODEL_DIR, local_files_only=os.path.isdir(MODEL_DIR))
        m.eval()
        if torch.cuda.is_available():
            m = m.to("cuda")
        elif os.environ.get("DEID_NER_INT8", "1") != "0":
            m = torch.quantization.quantize_dynamic(m, {torch.nn.Linear}, dtype=torch.qint8)
        _M = m
    return _M


def _worker_init():
    import torch
    torch.set_num_threads(int(os.environ.get("DEID_NER_THREADS", "1")))
    _load()


def _pack(lines):
    """Group normalised lines into chunks of <= CHUNK_WORDS words: [(text, [(line, offset)])]."""
    chunks, cur, off, words = [], [], 0, 0
    for n in lines:
        w = n.count(" ") + 1
        if cur and words + w > CHUNK_WORDS:
            chunks.append(("\n".join(x for x, _ in cur), cur))
            cur, off, words = [], 0, 0
        cur.append((n, off))
        off += len(n) + 1
        words += w
    if cur:
        chunks.append(("\n".join(x for x, _ in cur), cur))
    return chunks


def _infer_chunks(chunks):
    """[(text, [(line, offset)])] -> {key(line): [[s, e, kind, score]]} for every line (empty lists included)."""
    import torch
    m = _load()
    labels = list(LABELS)
    out = {}
    for i in range(0, len(chunks), BATCH):
        part = chunks[i:i + BATCH]
        with torch.inference_mode():
            try:
                preds = m.batch_predict_entities([t for t, _ in part], labels, threshold=THRESH)
            except Exception:
                preds = []
                for t, _ in part:
                    try:
                        preds.append(m.predict_entities(t, labels, threshold=THRESH))
                    except Exception:
                        preds.append([])
        for (t, lines), ents in zip(part, preds):
            for n, off in lines:
                out.setdefault(key(n), [])
                for e in ents:
                    s, en = e["start"] - off, e["end"] - off
                    if 0 <= s < en <= len(n):
                        out[key(n)].append([s, en, LABELS.get(e["label"], e["label"]), round(float(e["score"]), 3)])
    return out


# ------------------------------------------------------------------ filters
_FILTERS = None


def _filters():
    global _FILTERS
    if _FILTERS is None:
        tools = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")
        sys.path.insert(0, tools)
        try:
            import nerpass
            import nergate
            _FILTERS = (nerpass.keep, nerpass.norm, nergate.drop)
        except Exception:
            _FILTERS = (lambda label, v: len(v) >= 3, lambda label, v: v.strip(), lambda kind, v: None)
    return _FILTERS


def accept(kind: str, value: str) -> bool:
    keep, norm, drop = _filters()
    lab = _KEEP_LABEL.get(kind, kind)
    v = norm(lab, value)
    return bool(v) and keep(lab, v) and drop(kind, v) is None


# ------------------------------------------------------------------ public API
def _split(text: str):
    """[(line_offset, normalised, imap)] for useful lines."""
    res, off = [], 0
    for line in text.split("\n"):
        n, imap = _norm(line)
        if _useful(n):
            res.append((off, n, imap))
        off += len(line) + 1
    return res


def prefetch(texts, workers: int | None = None, log=None) -> int:
    """Run the model on every not-yet-cached line of `texts` (multiprocess). Returns #lines inferred."""
    seen, todo = set(), []
    for t in texts:
        if not t:
            continue
        for _, n, _ in _split(t):
            k = key(n)
            if k not in seen:
                seen.add(k)
                todo.append(n)
    have = cache_get([key(n) for n in todo])
    todo = [n for n in todo if key(n) not in have]
    if not todo:
        return 0
    chunks = _pack(todo)
    groups = [chunks[i:i + BATCH] for i in range(0, len(chunks), BATCH)]
    try:
        import torch
        gpu = torch.cuda.is_available()
    except ImportError:
        return 0
    if gpu or (workers or 0) == 1 or len(groups) < 4:
        for j, g in enumerate(groups):
            cache_put(_infer_chunks(g))
            if log and j % 50 == 0:
                log(f"ner {j}/{len(groups)}")
        return len(todo)
    import multiprocessing as mp
    workers = workers or min(32, os.cpu_count() or 4)
    with mp.get_context("spawn").Pool(workers, initializer=_worker_init, maxtasksperchild=200) as pool:
        for j, res in enumerate(pool.imap_unordered(_infer_chunks, groups)):
            cache_put(res)
            if log and j % 50 == 0:
                log(f"ner {j}/{len(groups)}")
    return len(todo)


def detect(text: str, filter: bool = True, run_missing: bool = True, min_score: float = THRESH):
    """[(start, end, kind)] entity spans in `text` (offsets into `text`), sorted, non-overlapping."""
    if not text or not _LETTER.search(text):
        return []
    lines = _split(text)
    if not lines:
        return []
    got = cache_get([key(n) for _, n, _ in lines])
    miss = [n for _, n, _ in lines if key(n) not in got]
    if miss and run_missing:
        try:
            res = _infer_chunks(_pack(list(dict.fromkeys(miss))))
            cache_put(res)
            got.update(res)
        except ImportError:
            pass
    spans = []
    for off, n, imap in lines:
        for s, e, kind, score in got.get(key(n), []):
            if score < min_score or e > len(imap):
                continue
            a, b = off + imap[s], off + imap[e - 1] + 1
            if filter and not accept(kind, text[a:b]):
                continue
            spans.append((a, b, kind))
    spans.sort(key=lambda x: (x[0], -(x[1] - x[0])))
    out, end = [], -1
    for s in spans:
        if s[0] >= end:
            out.append(s)
            end = s[1]
    return out
