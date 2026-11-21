"""Generate the submission README.txt (run steps, limitations, defects)."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

TEMPLATE = """MACHINA CAD DE-ID - SUBMISSION NOTES ({attempt})
==================================================

Pipeline source: code/ (MIT licensed). Python {py}; exact dependency versions in
code/requirements.lock. Source repository: github.com/viktor-lorentz/machina-cad-deid

HOW TO RUN
----------
  python3.12 -m venv .venv && . .venv/bin/activate
  pip install -r code/requirements.lock && cd code
  export DEID_SECRET=<private secret>        # seeds the pseudonyms; kept private
  python -m deid.cli harvest INPUT -o registry/candidates.json
  python -m deid.cli build-registry registry/candidates.json -o registry/registry.json
  python -m deid.cli rewrite INPUT OUTPUT/corpus --registry registry/registry.json {flags}
  python -m deid.cli leakscan OUTPUT/corpus --registry registry/registry.json
Run on a case-sensitive filesystem. The registry (original -> pseudonym map)
is private and is not part of this submission.

WHAT IT DOES
------------
1. Harvests identities (people, companies, accounts, emails, domains,
   identifying project names) from paths, STEP headers and PERSON/ORGANIZATION
   entities, PDF Info/XMP, IGES global section, FreeCAD/3MF XML metadata,
   OLE property sets (Inventor, Solid Edge), DXF header, Creo headers, and
   e-mail/URL/user-path patterns.
2. Assigns every identity ONE deterministic pseudonym with the same length and
   layout as the original (letters -> pronounceable letters, digits -> digits,
   separators kept; case follows each occurrence). Same identity -> same
   pseudonym everywhere; distinct identities -> distinct pseudonyms.
3. Rewrites contents format-aware: text formats (STEP, IGES, SAT, DXF, SVG,
   OBJ, WRL, ...), STL headers, zip containers (FCStd, 3MF, F3D) member by
   member, PDF objects/strings/streams via qpdf, OLE property streams.
   Because pseudonyms keep byte length, geometry, offsets, length-prefixed
   strings and fixed-size binary structures are unchanged.
{rename_note}4. Every rewritten file is validated (zip CRC, PDF page count, OLE
   structure); if validation fails, a conservative mode is tried, then the
   original bytes are kept and listed below.

LIMITATIONS
-----------
- Identifiers inside compressed proprietary streams (SolidWorks 2015+ parts,
  DWG, JT, Parasolid binary) are not rewritten in this attempt; only their
  file and folder names are handled.
- Text inside raster images and logos is not altered in this attempt.
- Vendor/software names (CAD systems, standards bodies, XML namespaces) are
  treated as non-identifying engineering information and left unchanged.

SOURCE DEFECTS (input files that are empty or invalid; kept, not dropped)
-------------------------------------------------------------------------
{defects}

FILES KEPT WITH ORIGINAL BYTES AFTER A FAILED REWRITE
-----------------------------------------------------
{fallbacks}

SUMMARY
-------
{summary}
"""


def write(attempt: str, results_json: str, registry_json: str, out: str, flags: str, py: str) -> None:
    results = json.loads(Path(results_json).read_text())
    reg = json.loads(Path(registry_json).read_text())
    newpath = {r: n for r, n, _ in results}
    defects = sorted(newpath.get(p, p) for p, why in reg.get("defects", {}).items())
    fallbacks = sorted((n, s) for _, n, s in results if s.startswith("fallback"))
    st = Counter(s.split(":")[0] for _, _, s in results)
    Path(out).write_text(TEMPLATE.format(
        attempt=attempt,
        py=py,
        flags=flags,
        rename_note=("   File and folder names go through the same registry; references\n"
                     "   between files are rewritten with the same mapping, so links stay\n"
                     "   consistent.\n") if "--rename" in flags else "",
        defects="\n".join(f"  empty file (0 bytes): {d}" for d in defects) or "  none found",
        fallbacks="\n".join(f"  {n}  ({s})" for n, s in fallbacks) or "  none",
        summary=f"  files: {len(results)}; rewritten: {st['changed']}; unchanged (no identifiers "
                f"found): {st['same']}; fallback: {st['fallback']}",
    ))
