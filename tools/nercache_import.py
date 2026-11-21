#!/usr/bin/env python3
"""Pre-fill the nerdetect line cache from the full-corpus nerpass run (agent C).
usage: nercache_import.py /data/ner/work/packed.jsonl /data/ner/work/preds.jsonl
Every line of a predicted chunk gets an entry (empty list = no entity), so later builds skip the model."""
import bisect
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from deid import nerdetect as nd  # noqa: E402


def main():
    packed, preds = sys.argv[1], sys.argv[2]
    ents = {}
    for l in open(preds):
        r = json.loads(l)
        ents[r["h"]] = r["ents"]
    items, nlines, nspans = {}, 0, 0
    for l in open(packed):
        r = json.loads(l)
        if r["h"] not in ents:
            continue
        t = r["text"]
        offs = [o for o, _ in r["lines"]]
        bounds = offs[1:] + [len(t)]
        lines = []
        for o, b in zip(offs, bounds):
            raw = t[o:b].rstrip("\n")
            n, imap = nd._norm(raw)
            inv = {orig: ni for ni, orig in enumerate(imap)}
            lines.append((o, raw, n, inv))
            if nd._useful(n):
                items.setdefault(nd.key(n), [])
        for lab, _txt, s, e, score in ents[r["h"]]:
            i = bisect.bisect_right(offs, s) - 1
            if i < 0:
                continue
            o, raw, n, inv = lines[i]
            rs, re_ = s - o, e - o
            if re_ > len(raw) or rs not in inv or (re_ - 1) not in inv or not nd._useful(n):
                continue
            items[nd.key(n)].append([inv[rs], inv[re_ - 1] + 1, nd.LABELS.get(lab, lab), score])
            nspans += 1
        nlines += len(lines)
        if len(items) > 200_000:
            nd.cache_put(items)
            items = {}
    nd.cache_put(items)
    n = nd._db().execute("SELECT count(*) FROM ner").fetchone()[0]
    print(f"lines seen {nlines}, spans {nspans}, cache rows {n}")


if __name__ == "__main__":
    main()
