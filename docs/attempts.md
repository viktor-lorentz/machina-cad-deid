# Attempt log

Baseline (input copied unchanged): 292 / 1000.

| # | Time (ET) | Change | Total | Category scores | Notes |
|---|-----------|--------|-------|-----------------|-------|
| 1 | Fri 22:49 | content-only (build 1b, e68bd4d) | **265** | leak 0/20, pseudo-consistency 1/15, distinct 2/10, relationships 11/20 (2 n/c), eng-preservation 10/15, OLE hidden 2/10, packaging 5/10 (2 n/c), **scoped PDF removal 0/300**, **PDF same-identity consistency 0/200**, **non-collision triplets 0/100**, drawing/model correspondence 182/200, OLE saved-account 1/25, OLE cross-stream residue 1/25, OLE preview 25/25, OLE integrity 25/25 | 600 pts are PDF text; lost 18 on drawing/model vs baseline (likely renamed-in-content but not in paths) |
| 2 | Sat 02:13 | + path renames + zip recursion (ebde0e6) | **266** | same as #1 except leakage 1/20 | renames safe (relationships unchanged); PDF stream corruption bug present in #1-#2 |
| 3 | Sat 03:32 | PDF corruption fix + PDF page text + OLE in-place props + registry v2 (9c56746) | **397** | leak 5/20, consistency 4/15, distinct 3/10, relationships 11/20 (2 n/c), eng 10/15, OLE hidden 2/10, packaging 5/10 (2 n/c), **PDF removal 86/300**, **PDF consistency 40/200**, **non-collision 4/100**, drawing/model 175/200 (−7), OLE saved-account 1/25, OLE residue 1/25, OLE preview 25/25, OLE integrity 25/25 | gaps: PDF removal 214, PDF consistency 160, non-collision 96, drawing/model 25, OLE saved 24, OLE residue 24, leak 15 |
| 4 | Sat 04:01 | + OLE full-stream replacement, wrapped PDF names, license-prose filter (4763b59) | **395** | same as #3 except PDF consistency 39/200 (−1), drawing/model 174/200 (−1); OLE saved/residue unchanged 1/25 | OLE changes did not reach the scorer's sampled values |

## Attempt 5 — 508 (BB-E3346D04, Sat 8:15 AM ET)
registry6 recall pass (GT recall 18% -> 59%), extension-safe renames, middle-band redaction, compositional pseudonyms, OLE field rewrite.
leak 9/20 · consistency 5/15 · distinct 2/10 · relationships 11/20 · engineering 10/15 · OLE hidden 4/10 · packaging 3/10 ·
PDF removal 163/300 · PDF consistency 71/200 · triplets 22/100 · drawing/model 154/200 · OLE acct 2/25 · OLE residue 2/25 · OLE preview 25/25 · OLE integrity 25/25
Gaps (max-ours): PDF removal 137, PDF consistency 129, triplets 78, drawing/model 46, OLE acct 23, OLE residue 23.
Regressions vs a3: drawing/model -21, packaging -2, distinct -1.

## Attempt 6 — 561 (BB-2440305E, Sat 9:19 AM ET)
registry8: paths exclude part numbers (native renames 2023 -> 399), part precision, project coinages, .co.nz email fix, US phones.
leak 8/20 · consistency 4/15 · distinct 3/10 · relationships 11/20 · engineering 10/15 · OLE hidden 4/10 · packaging 5/10 ·
PDF removal 174/300 · PDF consistency 93/200 · triplets 31/100 · drawing/model 164/200 · OLE acct 2/25 · OLE residue 2/25 · preview 25 · integrity 25
Gaps: PDF removal 126, PDF consistency 107, triplets 69, drawing/model 36, OLE acct 23, OLE residue 23.
