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

## Sat 08:45 ET — attempt 5 = 508 (+111)
- Drawing/model 175 -> 154: native CAD basenames renamed 118 (a3) -> 2023 (a5) by part-number identities; SW/Inventor
  refs inside compressed streams break. Attempt 6: path mapper excludes kind=part (content still replaced).
- Part precision: drop pure-digit (LEGO catalogue), <6 chars (HX711, 0P01C fragments), non-ASCII part codes.
- Project coinages (AdvLIGO, mesoSPIM, BeBoPr++) with plain-word CamelCase filter (BasePlate, microSD, alloys).
- GT recall registry7: 61% (70% excl vendor); person 75%.
- Next gaps: PDF removal 137, PDF consistency 129, triplets 78. Unknown emails (100) + phones (46) in pdfeval -> harvest them.

## Sat 10:10 ET — attempt 6 = 561 (+53)
- drawing/model 154 -> 164 after removing part numbers from paths. a7: stems only person/account/email/domain/phone.
- OLE: identity fields 99% rewritten already; but 32% of OLE files kept the same value in OTHER streams
  (SW Header2, ISolidWorksInformation, Contents/*, Inventor UFRxDoc). a7: per-file field-value mapper over all streams
  -> residue 11% on a 1200-file sample, sizes unchanged.
- 39/46 strict-checker "unknown phones" are our own pseudonyms (checker artifact).
- ~65% of sampled SolidWorks files are 2015+ non-OLE containers: untouched internals (IDEAS: SW container).
- 10:00 CAUGHT before shipping: registry9 had "xmlns" (domain-acronym rule on xmlns.com) -> would corrupt every XML/SVG/3MF.
  Guard: FORMAT_WORDS never registered AND filtered at load_mappers (test added). Also role mailboxes (contact@, info@)
  no longer become accounts. attempt-7 restarted on registry10 (+aLIGO).
- SW2015+ (non-OLE, ~65% of SW files): 255/257 sampled have registry identities inside raw-deflate sections
  (marker 14 00 06 00 08 00). Untouched today -> next big lever after a7 (needs inflate/patch/deflate + size fields).
- strict-checker artifacts: "no-pseudonym" Magnus case (pseudonym present), S. Aston vs S.Aston collisions.
- 10:00 swx.py (SW2015+): record = MARK|4B|crc32(u)|csize|usize|namelen|nibble-swapped name|raw deflate.
  Rewrite: same-length replace, recompute CRC, recompress, pad zeros to csize (file length + offsets unchanged).
  500-file test: section hits 3475 -> 72, 0 errors, all same length. Harvest docProps core/custom (creator,
  lastModifiedBy, drawn/checked by) as *_field. -> attempt 8 (needs re-harvest).

## Sat 11:00 ET — attempt 7 = 562 (+1)
- OLE acct 2->4, residue 2->4. drawing/model flat at 164 despite native renames 399->131 -> renames are NOT the cause.
  Hypothesis: part numbers replaced in drawing text, model file keeps original name. A/B in attempt 9 via
  DEID_KEEP_FILE_CODES=/data/registry/stems.txt (parts 4901 -> 3161, GT part recall 76% -> 63%).
- attempt 8 = a7 + swx + SW docProps harvest. Caught twice before shipping: junk field values ("-.01", dates, NA)
  and per-file propagation of "Author"/"Owner"/"ISO 2768" (would rename XML property names). Now: field_ok +
  propagation only for person/account values, PROP_WORDS excluded.

## Sat 12:30 ET — a8 553, a9 519 (best still a7 562)
- SW2015 rewrite: no category gained; packaging 5->2 (scope? padded/recompressed sections). OFF.
- keep-file-codes: drawing/model +3, PDF consistency -20, triplets -8. REJECTED. Part-number replacement is worth a lot
  in the PDF categories; the drawing/model gap is something else (maybe paired drawing/model metadata, not names).
- free "First Last" rule (registry12): GT recall unchanged (names already caught), adds Robert Bosch / Alfred Gessow
  Rotorcraft -> not shipped.
- code/ quoted corpus strings (tests, IDEAS, docs/AGENTS.md). Now dropped from code/; source stays exact.
- attempt 10 = registry10 (a7) + swx off + restricted propagation + clean code/: tests packaging 2 -> >=5.

## Sat 14:20 ET — KPI = PDF recall r (user): PDF pts ~ 300r + 200r^2 + 100r^3. Leader ~852, #2 698, we 562 (13th).
- Every attempt from now: highest-gt_recall registry that keeps pdfeval scope not worse. Always keep next attempt building.
- registry13 (family codes FD-JL-*, 30DOSTE, PPSTE, MS-*, HUNSLET-45-*): GT 64% -> 67%, parts 76 -> 87%. = attempt 11.
- harvest14 adds addresses / 00-intl phones / DRAUGHTING-ENGINEERING firms / Advanced LIGO.
- rewrite coverage: only ~1% of PDFs with registry hits stay unreduced (6/467), 7% partial -> registry recall is the lever.
- Last submit by 5:00 AM PT Sunday (grading up to 3 h).
