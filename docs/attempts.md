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

## Attempt 7 — 562 (BB-5900CE8E, Sat 10:23 AM ET)
registry10; file stems only person/account/email/domain/phone (native renames 399 -> 131); OLE per-file field propagation; FORMAT_WORDS guard.
leak 9/20 · consistency 5/15 · distinct 3/10 · relationships 11/20 · engineering 10/15 · OLE hidden 4/10 · packaging 5/10 ·
PDF removal 175/300 · PDF consistency 89/200 · triplets 29/100 · drawing/model 164/200 · OLE acct 4/25 · OLE residue 4/25 · preview 25 · integrity 25
Finding: native renames 399 -> 131 did NOT move drawing/model (164). Remaining -11 vs a3 likely = part numbers replaced in
drawing text while the model file keeps its original name (paths exclude parts since a6).

## Attempt 8 — 553 (BB-9ACD7430, Sat 11:30 AM ET)
a7 + SolidWorks 2015+ section rewrite + SW docProps harvest (registry11).
leak 9 · consistency 5 · distinct 2 (-1) · relationships 10 (-1) · engineering 10 · OLE hidden 4 · packaging 2 (-3) ·
PDF removal 175 · PDF consistency 89 · triplets 29 · drawing/model 160 (-4) · OLE acct 4 · residue 4 · preview 25 · integrity 25
Verdict: SW2015 rewrite is net negative (-9), no category gained. Disabled (G["swx"]=False) from attempt 10 on.

## Attempt 9 — 519 (BB-0501A3F6, Sat 11:57 AM ET)
a8 + DEID_KEEP_FILE_CODES (part codes that also name files are kept).
leak 8 (-1) · consistency 4 (-1) · distinct 2 · relationships 10 · engineering 10 · OLE hidden 4 · packaging 2 ·
PDF removal 168 (-7) · PDF consistency 69 (-20) · triplets 21 (-8) · drawing/model 163 (+3) · OLE 4/4/25/25
Verdict: rejected. Part-number replacement drives the PDF consistency/triplet checks far more than drawing/model.
Packaging 2/10 in both a8 and a9 (a7: 5): suspect code/ quoting corpus strings (tests, IDEAS.md, docs) -> attempt 10
drops those from code/ with the source kept exact.

## Attempt 10 — 562 (BB-BBCA09DC, Sat 1:46 PM)
registry10 (= a7) + swx off + propagation person/account only + code/ without notes/tests.
Identical to a7 in every category (packaging 5). => the a8/a9 packaging drop (5 -> 2) came from the SW2015 rewrite, not code/.

## Attempt 13 — 512 (BB-90430234, Sat 3:49 PM)
registry15 + part-number file-stem renames (non-native) + native files keep part refs + multi-line STEP strings.
leak 8 · consistency 4 · distinct 2 · relationships 11 · engineering 10 · OLE hidden 4 · packaging 3 (-2) ·
PDF removal 163 (-12) · PDF consistency 68 (-21) · triplets 21 (-8) · drawing/model 160 (-4) · OLE 4/4/25/25
Verdict: part-number stem renames break file location (same signature as a5: renaming by part numbers). Reverted
(part_stems off). Lesson: NEVER rename file stems by part numbers; the grader locates files by name.

## Attempt 14 — 609 NEW BEST (BB-DE9A89BE, Sat 5:11 PM)
registry17 (r16 + cleaned NER; GT RAND 66%) + OLE free-sector scrub + every saved account/author pseudonymised (C's olezlib +
user-path mapper) + native files keep part refs; part-stem renames reverted; merged vendor/NER names content-only.
| category | a10 | a13 | **a14** | target |
|---|---|---|---|---|
| Original identifier leakage | 9 | 8 | 9 /20 | |
| Pseudonym consistency | 5 | 4 | 4 /15 | |
| Distinct identities stay distinct | 3 | 2 | 3 /10 | |
| Relationships and references | 11 | 11 | 11 /20 | |
| Engineering information preservation | 10 | 10 | 10 /15 | |
| Native OLE streams and hidden surfaces | 4 | 4 | 6 /10 | |
| Packaging, scope and repeatability | 5 | 3 | 5 /10 | |
| Scoped PDF identifier removal | 175 | 163 | 179 /300 | 285 |
| Same-identity consistency across PDFs | 89 | 68 | 90 /200 | 180 |
| Identity non-collision triplets | 29 | 21 | 29 /100 | 85 |
| Drawing/model correspondence | 164 | 160 | 165 /200 | 195 |
| OLE saved-account pseudonymization | 4 | 4 | **24** /25 | 22 |
| OLE cross-stream identity residue | 4 | 4 | **24** /25 | 22 |
| OLE preview consistency | 25 | 25 | 25 /25 | |
| OLE container integrity | 25 | 25 | 25 /25 | |
| **total** | 562 | 512 | **609** | 880 |
Verdict: OLE fix = +40 (target met). Paths fix restored a10 levels. Recall 61 -> 66% gave PDF removal +4 only.

## Attempt 15 — 309 (BB-445D755C, Sat 6:31 PM): PDF text rewrites reverted by the render-warning guard
registry19c (GT 85%) + a14 code. With the bigger registry nearly every text-layer PDF rewrite (redaction + insert) raised
the benign MuPDF note "unknown font format, guessing type1" -> `_pdf_render_warnings` guard reverted the PDF to the original
(7,152 PDFs unchanged vs 1,288 in a14; B's e2e GT recall 14% vs 71%).
leak 0 · consistency 1 · distinct 2 · relationships 11 · engineering 10 · OLE hidden 6 · packaging 5 · PDF removal 1 ·
PDF consistency 0 · triplets 0 · drawing/model 175 (+10: drawing PDFs untouched) · OLE 24/24/25/25
Lessons: (1) PDF checks are near all-or-nothing per check: e2e 14% -> 1/300, 71% -> 179/300. (2) drawing/model goes UP when
drawing PDFs are left alone (175 vs 165; baseline 182) -> the d/m loss comes from drawing-PDF text edits.
Fix eed7dd0 (benign notes ignored). a16 (same regression) not submitted.
