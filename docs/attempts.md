# Attempt log

Baseline (input copied unchanged): 292 / 1000.

| # | Time (ET) | Change | Total | Category scores | Notes |
|---|-----------|--------|-------|-----------------|-------|
| 1 | Fri 22:49 | content-only (build 1b, e68bd4d) | **265** | leak 0/20, pseudo-consistency 1/15, distinct 2/10, relationships 11/20 (2 n/c), eng-preservation 10/15, OLE hidden 2/10, packaging 5/10 (2 n/c), **scoped PDF removal 0/300**, **PDF same-identity consistency 0/200**, **non-collision triplets 0/100**, drawing/model correspondence 182/200, OLE saved-account 1/25, OLE cross-stream residue 1/25, OLE preview 25/25, OLE integrity 25/25 | 600 pts are PDF text; lost 18 on drawing/model vs baseline (likely renamed-in-content but not in paths) |
| 2 | Sat 02:13 | + path renames + zip recursion (ebde0e6) | **266** | same as #1 except leakage 1/20 | renames safe (relationships unchanged); PDF stream corruption bug present in #1-#2 |
