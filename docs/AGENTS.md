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
