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
