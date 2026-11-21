"""PDF page-text checks (agent B), mirroring the server's 600 PDF points.

For each sampled input PDF, find registry identities in the *rendered page
text* (PyMuPDF), then look at the same page of the output PDF:

* removed:    the original string no longer appears in the output page text;
* consistent: the expected pseudonym (the one the registry assigns, so the
              same everywhere) appears in the output page text;
* distinct:   no two different identities appear under the same pseudonym
              across all sampled pages (collisions counted globally).

Whitespace is normalised and matching is case-insensitive, because page text
extraction splits and re-spaces spans.
"""

from __future__ import annotations

import re
from collections import defaultdict

_WS = re.compile(r"\s+")


def page_texts(path: str, max_pages: int = 6) -> list[str]:
    import fitz

    out = []
    try:
        with fitz.open(path) as doc:
            for i, page in enumerate(doc):
                if i >= max_pages:
                    break
                out.append(_WS.sub(" ", page.get_text("text")).lower())
    except Exception:
        pass
    return out


def check_pair(src: str, dst: str, mapper) -> dict:
    """Counts for one input/output PDF pair; `mapper` is the registry Mapper (allm)."""
    res = {"occ": 0, "removed": 0, "consistent": 0, "pairs": set()}
    a, b = page_texts(src), page_texts(dst)
    for i, ta in enumerate(a):
        tb = b[i] if i < len(b) else ""
        seen = set()
        for _, _, key in mapper.find(ta.encode("ascii", "ignore")):
            if key in seen:
                continue
            seen.add(key)
            pseudo = mapper.entries[key].lower()
            res["occ"] += 1
            if not re.search(r"(?<![a-z0-9])" + re.escape(key) + r"(?![a-z0-9])", tb):
                res["removed"] += 1
            if pseudo in tb:
                res["consistent"] += 1
                res["pairs"].add((pseudo, key))
    return res


def collisions(pairs) -> int:
    by_pseudo = defaultdict(set)
    for p, k in pairs:
        by_pseudo[p].add(k)
    return sum(len(v) - 1 for v in by_pseudo.values() if len(v) > 1)
