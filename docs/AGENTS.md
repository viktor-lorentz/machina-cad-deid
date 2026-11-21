# Agent coordination (read before editing; update your row when you start/finish)

Two Claude agents work on this repo. To avoid collisions each owns files; touch others' files only after noting it here.

| Agent | Branch / worktree | Owns | Status |
|-------|-------------------|------|--------|
| CAD agent A (pipeline) | `main` in ~/machina-cad-deid | harvest, registry/, rewrite.py, formats/, readme.py, infra/, attempts | active |
| CAD agent B (checker) | `checker` in ~/machina-cad-deid-checker | deid/checker.py, deid/leakscan.py, new deid/detect/ (independent detectors), tests/test_checker*.py, tests/test_leak*.py | detectors + fingerprints + strict score done (branch `checker`, 22 tests pass); consistency (duplicates, references) done too; ready to merge into main |

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
