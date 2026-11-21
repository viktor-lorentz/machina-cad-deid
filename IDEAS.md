# Ranked experiment backlog (Machina CAD De-ID)

1. Attempt 1: full harvest on VM -> build-registry -> rewrite (contents only, no renames) -> leakscan -> upload (needs token from Viktor).
2. Attempt 2: + `--rename` path renames (owner__repo, web domains, catalog names).
3. + `--archives` recursion for .zip; add .gz/.Z/tar handlers.
4. SolidWorks 2015+ container: parse sections, inflate, same-length patch, deflate (timebox 4 h).
5. PDF page text + images (OCR/logos), embedded previews/thumbnails in FCStd/3MF/OLE.
6. Registry precision/recall tuning from leakscan top-leakers; institution names inside catalog names.
7. Generate README.txt (run steps, defects list from harvest, fallbacks).

## Status notes (Sat 2026-11-21 ~22:45 ET)
- Upload speed from VM: ~245 MB/s -> full attempt (131 GB, 189k objects) ~10 min. Start the final upload by 09:30 ET.
- Remaining leaks after attempt 2: SolidWorks (compressed sections), PDF fallbacks (PdfError 107), F3D, DWG, Solid Edge .par, CATIA, STL binary headers?, zip fallbacks.
- SolidWorks container: section signature 14 00 06 00 08 00, then per-file 4-byte key, 3 obfuscated size fields (x4,x1,x2 of one value), name len, nibble-rotated name, raw-deflate payload.

## Sat 03:15 ET findings
- Attempt-1 server: 265. 600 pts = PDF page text (0 so far); OLE saved-account 1/25; drawing/model 182/200.
- BUG (attempts 1-2): rw_pdf wrote decoded bytes with /FlateDecode -> corrupt streams/fonts. Fixed + render-warning fallback.
- Done: PDF page text harvest + redaction replace; OLE in-place mini-stream writes + OLEPS harvest.
- Next: SolidWorks container; PDF text consistency across PDFs (names split across text spans may be missed by search_for); images/OCR.

## Sat 04:50 ET — after attempt-3 = 397
Gaps (max-ours): PDF removal 214, PDF consistency 160, non-collision 96, drawing/model 25 (regressed 182->175), OLE saved-account 24, OLE residue 24, leak 15, consistency 11.
- attempt-4 (submitted): OLE full-stream replacement, wrapped PDF names, license-prose filter.
- attempt-5 (building): near-label surnames in PDF title blocks (repo-local filter), middle-band redaction (spares neighbour lines), per-line pseudonym slices, OLE field-level author/last-saved-by incl. cp1252 + generic accounts (scope=field).
- TODO: drawing/model regression — suspect title-block part names/numbers replaced in PDF but not in model (or vice versa). Investigate pairs.
- TODO: org acronyms (IIT, COSMIIC, NNP) and "RELEASED BY X".
- attempt-4 = 395. OLE categories flat because surviving OLE field values were generic/filtered accounts
  ('map' 901 files, Administrator 319, Operator 240, LECOMTE, 09737602, Beep, portable, Séba cp1252): attempt-5 field scope fixes.
- drawing/model drop is NOT renames (native basename renames 864 (#2) vs 892 (#3)); suspect full-height redaction boxes (fixed in #5).
- CJK names (e.g. 黄海生) cannot get same-length pseudonyms yet (generator only maps a-z/0-9).

## Sat 08:00 ET — recall pass (agent B ground truth, gt_recall.py, 122 ids)
- registry3 18% -> registry6 59% (67% excl vendors): part-number 0->84%, institution 15->85%, person 30->50%, phone 0->67%.
- First attempt-5 build discarded: near-label junk (Colour/Remap/Extru) global; and a PDF perf trap (per-hit textpage rebuild).
- Remaining misses: single surnames in rev tables (Taylor, Moore), first names not in list, projects (AdvLIGO, COSI, BeBoPr++), addresses, acronyms (DTU MPP, IRP), vendors (by design).
- 08:00 attempt-5 build #2: LOCAL 982 but 38 SLDDRW files got their EXTENSION pseudonymised (part number "LCSAP-101.SLDDRW").
  Fixed: map_path never touches the extension; part values strip file extensions. Also interleaved two-column
  institution junk ("Technology Massachusetts Institute") caused 230 'technology' scope-changes -> filtered.
- Strict pdfeval scope-change: a3 333, a4 577, a5#2 696. ~200 of a5's are accented identities (Amigó, Fundació, für)
  that the checker can't see (ascii-ignore) -> artifact, not a real regression.
