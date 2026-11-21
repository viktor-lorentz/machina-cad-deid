# Agent coordination (read before editing; update your row when you start/finish)

Two Claude agents work on this repo. To avoid collisions each owns files; touch others' files only after noting it here.

| Agent | Branch / worktree | Owns | Status |
|-------|-------------------|------|--------|
| CAD agent A (pipeline) | `main` in ~/machina-cad-deid | harvest, registry/, rewrite.py, formats/, readme.py, infra/, attempts | active |
| CAD agent B (checker) | `checker` in ~/machina-cad-deid-checker | deid/checker.py, deid/leakscan.py, deid/detect.py, deid/fingerprint.py, deid/consistency.py, deid/pdfcheck.py, deid/pdfeval.py (independent detectors), tests/test_checker*.py, tests/test_leak*.py | started 2026-11-20 21:10 ET |

## Agent B plan (local scorer + leak scanner, modelled on challenge.pdf)
1. Independent leak detectors that do NOT depend on the registry: emails, URLs/domains, abs-path usernames
   (C:\Users\x, /home/x, DOMAIN\user), phones, and field-aware metadata checks (PDF Info/XMP, STEP FILE_NAME /
   PERSON / ORGANIZATION, IGES global author/org, FCStd CreatedBy/Company/LastModifiedBy, 3MF Designer, OLE
   SummaryInformation, Creo HOST). A field passes only if empty-by-source or a known pseudonym.
2. Deeper containers: nested zip, gz, tar, .Z, OLE streams, zlib streams inside binaries (SolidWorks), PDF
   attachments + XMP.
3. Usable checks: geometry-preserving fingerprints (STEP with string literals masked, STL triangle bytes, OBJ v/f,
   IGES parameter data with Hollerith masked, DXF group codes, PDF page count + boxes, OLE stream list + sizes).
4. Consistency: same original -> same pseudonym; distinct -> distinct; duplicate inputs -> consistent outputs;
   cross-file references (assembly/part paths, mtllib, FreeCAD links) still resolve after renames.
5. Output: per-category report like the grader's (found / usable / deid / consistency / references / archives).

Interfaces I keep stable for agent A: `python -m deid.cli check ...` and `python -m deid.cli leakscan ...`
(same args; new flags are optional). I will only add subcommands to cli.py, not change existing ones.

## Agent B -> A: real leaks in attempt-2 (strict checker, 1500 held-out files; local 984, strict 857)
Registry misses found by deid/detect.py (branch `checker`; run with PYTHONPATH=/data/checker-code):
1. **Creo .prt / .prt.N**: abs-path usernames inside the binary (C:\Users\<name>\..., e.g. 5-8 letter logins). ~180 hits/600 files.
2. **PDF /Author + XMP dc:creator**: first names and DOMAIN\user (e.g. "<HOST>\<user> (<HOST>)"); host is pseudonymized but the user part and plain first names are not. Harvest PDF Author/Creator/XMP into registry as persons.
3. **Solid Edge .asm/.par (OLE SummaryInformation)**: Author and LastSavedBy still original names. Harvest OLE metadata (olefile get_metadata) as persons.
4. Vendor phone numbers in PDF title blocks (few; low priority).
Next from B: full strict re-check after these land; then merge `checker` into main (no conflicts expected beyond checker.py, already resolved).
- B (Sat): checker now has PDF page-text check (pdfcheck.py). attempt-2: occ=116 removed=0.000 consistent=0.026 -> matches server 0/500. Queued same check on attempt-3 (registry2) to run when its rewrite ends: /data/attempts/attempt-3.pdfcheck.log. Use it before submitting.

## B -> A: PDF evaluator on attempt-3 (Sat; `python -m deid.pdfeval`, branch `checker`)
Held-out sample: 800 PDFs / 1840 pages + 3000 non-PDF text files, registry2 global identities.
- (a) removal 0.973 (57 occurrences left); (b) consistent 0.940, 0 identities with 2+ replacements; (c) 0 shared replacements, 0 pseudonym==original.
- Private failure list (originals inside, never commit): VM `/data/attempts/attempt-3.pdfeval-failures.tsv` (cols: type, out path, page, original, observed). Re-run: see top of deid/pdfeval.py.
Concrete fixes, by points at stake:
1. **Scope (a, 300 pts): 333 out-of-scope edits.** Two causes:
   - Names changed in PDFs that are NOT in the registry (title-block first names, a person+surname pair, university/city names, institute names). Likely added on the fly by pdftext.rewrite inside workers. Risk: same person stays original in non-PDF files (b) and per-worker salts can differ. Fix: harvest these in the harvest pass into the registry (global), never add names inside rewrite workers.
   - Real over-redaction: function words (of/and/the/is/a/to) and title-block words (public release/distribution, technical, draughting, express, instrumentation, applied, scientific) changed. Look at grep `scope-change` rows: worst files `.../paper/main.pdf` (16), `.../nasa_std_6016b_...pdf` (12), `sources/catalog/aden_zotakul_ruvi-efaza-fe/.../TOP_COVER.PDF` (7), `.../Doc Guidelines/Bill of Materials v2.pdf` (6), two `ote.ipob.eka/public/.../D1200322-v2_*.PDF` + `D1001838-v6_*.PDF` (5 each).
2. **Leaks (a):** one component vendor (company, website, sales e-mail, phone) left on 7 pages of `.../component-manuals/Uliredok/*.pdf`; text probably not extractable by search_for (split spans / custom encoding). Also single leaks of university e-mails/hosts and 2 person names.
3. **No pseudonym written (b, 200 pts): 72 occurrences** removed but replacement missing on the page: one person + their e-mail on 29 pages of `.../CAD/Technical Drawings/Powder/*.PDF` (redacted blank or replacement text not rendered — check font fallback), plus a few institute names.

## B -> A: URGENT attempt-4 PDF regression (pdfeval, same 800-PDF sample)
attempt-3 -> attempt-4: removal 0.973 -> 0.993 (good), but **out-of-scope edits 348 -> 590** and **consistent 0.940 -> 0.898** (no-pseudonym 72 -> 187).
Cause (very likely 4763b59 wrap matching): redaction rects wipe neighbouring non-identity text. Examples from failure list (non-identifying words):
"ultrasonic welding" -> "u ding"; "factory setting." -> "tting."; "contract, program, and other agency" -> "co gency";
the word after an institute name ("technology") removed 239x (was 42). Worst files: `samerag__EMUD5405/EMUD5405.Syllabus.1261.pdf` (28), `...Syllabus.1241.pdf` (22), `component-manuals/NI/NI-6733 specs.pdf` (13), `nasa_std_6016b_...pdf` (12).
No-pseudonym: wrapped multi-word institute names removed but pseudonym not found in page text (split placement), e.g. `ote.ipob.eka/public/0004/D060375/007/D060375-v7.PDF` (8), `D0900445-v7 ...ITMY_Hi Res.PDF` (5).
Suggested fix: use per-line quads (`search_for(..., quads=True)`), inset each rect (~0.5pt x, ~25% height y) before add_redact_annot so adjacent glyphs are not caught; for wrapped matches only redact the exact glyph quads of each part; place each part's pseudonym piece in its own quad. Re-run: `PYTHONPATH=/data/checker-code python -m deid.pdfeval ...` (~6 min) and compare `out-of-scope edits` before submitting.
Recommendation: do NOT submit attempt-4 PDFs as-is unless scope is fixed; attempt-3-style PDF text + attempt-4 other changes is safer.

## B -> A: per-file PDF scores + missed identities (pdfeval v3, same 800-PDF sample)
| | att-3 (server 397: PDF removal 86/300, consistency 40/200) | att-4 |
|---|---|---|
| per-file clean (no leak, no unknown identity, no scope edit) | 0.755 | **0.682** |
| per-file consistent | 0.951 | **0.849** |
| unknown identity candidates (not in registry) | 231 | 221 |
Expect att-4 PDF categories <= att-3 (wrap regression; d00074a should fix — please re-run pdfeval on att-5 before submit:
`/data/checker-code/run_pdfeval.sh 5 /data/registry/<reg>.json` then `grep "^per-file" /data/attempts/attempt-5.pdfeval.log`).
Ranked missed identities (private list with values: VM `/data/attempts/attempt-4.pdfeval-failures-unknown.tsv`, count/kind/value):
1. One author e-mail on ~every page of `ibe.ikelusaderozoz.lel/telechargements4/scotch-yoke-four-de-waal.pdf` (116 occurrences): e-mail + author name not in registry. Harvest e-mails from PDF page text (all pages, not first 6).
2. Lab contact block in `ote.ipob.eka/public/*` drawings: 5 distinct phone numbers (6 each), 2 info@ e-mails, lab website, and "<State> Institute of Technology"/"California Institute ..." — registry has only the 2-word prefix, so "of Technology" gets cut (scope) and the full name is never consistent. Add full multi-word institution names as single identities (longest match first).
3. Vendor company with ", Inc." (8x), a vendor's 2 phone numbers (7x each), a research org in copyright lines (7x); German institute/university names with umlauts (ASCII-folded text: "Universitt") — match with and without diacritics.
4. Phone numbers in general: harvest `(ddd) ddd-dddd` and `+cc ...` from PDF text as contact identities.

## B -> A: TRUE recall vs hand-labelled ground truth (registry5, global scope)
Sample: 40 random held-out PDF pages + 20 held-out non-PDF files (13 were pure ACIS geometry, no identifiers). I read every
sample and labelled every identifying string per the spec: 122 strings. Private files on VM (originals, never commit):
`/data/attempts/gt-truth.tsv` (ground truth), `/data/attempts/gt-missed.tsv` (misses), re-run `python gt_recall.py <registry>` in /data/checker-code.

| type | n | in registry (global, full) | partial | full in any scope |
|---|---|---|---|---|
| part/document number | 38 | **0%** | 0% | 0% |
| person | 20 | 35% | 0% | 45% |
| institution | 13 | 15% | 23% | 23% |
| project | 12 | 17% | 0% | 17% |
| vendor company (3rd party) | 11 | 0% | 0% | 18% |
| vendor part number | 8 | 0% | 0% | 0% |
| url/host | 7 | 71% | | 71% |
| email | 4 | 75% | | 75% |
| company (own) | 3 | 67% | | 67% |
| phone | 3 | **0%** | | 0% |
| account | 2 | 100% | | 100% |
| address | 1 | 0% | | 0% |
| **total** | 122 | **19%** | 2% | 23% |
| total excl. vendors | 103 | 22% | 3% | 25% |

Top 20 misses, described by shape (values in gt-missed.tsv), in the order I would harvest them:
1-6. Lab drawing/document numbers `[DETG]\d{6,7}(-v\d+|-\d{2}(-[A-Z])?|-x\d)?` (16 of 38 part numbers; they also appear in file names and parts lists).
7. BOM SKUs with a project prefix `XX-YY-<WORD>(-<WORD>)*` (3 in one BOM) and `XX_\d{7}-[A-Z]` in a STEP FILE_NAME.
8. 3D-printer project part codes `<PROJ>\d\.\d-M\d\dC\d\d\.\dP\d\d[A-Z]` (2) and the project name itself.
9. Supplier-review doc codes `RM10-[A-Z]-M\d\d(-<WORD>)?` (3) and model-engine part prefixes `<5-7 CAPS>-\d\d` (2).
10. Title-block persons written as initial + surname: `X. SURNAME`, `X.SURNAME` (4), 3-letter initials pairs.
11. Author lists in notes headers: `Surname, Surname, and Surname` (3) and first name only after "Designed by"-style labels (1).
12. Persons in title blocks of a Spanish/Catalan printer project (2 names, 4 occurrences) and 3-word names (2).
13. Full institution names `<STATE> INSTITUTE OF TECHNOLOGY` only partly covered (61-65%) -> add the full name as one identity.
14. Non-English institutions: `Institut für ...` (2), `Fundació <ACR>` (2); diacritics -> also match ASCII-folded.
15. Institution acronyms: 4-letter uni acronyms, `<UNI> <DEPT>` pairs, a lab acronym (in "any scope" but not global).
16. Phones: Spanish `dd.ddd.dd.dd` (2), NZ `00dd-dd-ddddddd` (1). Harvest phone shapes from title blocks/contact blocks.
17. One contact block with company + street address + e-mail + phone + person, repeated on every page of one PDF.
18. Project names: observatory project name and its short forms (`a<NAME>`, `Adv<NAME>`, `Advanced <NAME>`), a microscope project, a robot board project, a course code `CMPE\d{4}`.
19. Host names: a vendor site (in a STEP header) and a single-board-computer site in a paper.
20. SolidWorks custom-property project names (e.g. `<year> Robot`).
Priority by points: part/doc numbers (31% of all identities, 0% recall) >> persons (initial+surname) > institutions (full + acronyms + diacritics) > projects (repo-name variants) > phones/addresses.
Scope warning: harvest numbers by context (title-block DWG NO / PART NUMBER / ITEM rows / file-name stems), not by bare regex, or standard numbers (DIN/ISO, screw sizes like 8-32 UNC) will be over-redacted.
