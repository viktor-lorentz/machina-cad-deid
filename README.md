# machina-cad-deid

A reproducible pipeline that de-identifies a large engineering/CAD corpus
(PDFs, drawings, STEP/IGES/SAT, SolidWorks, Inventor, FreeCAD, meshes, archives)
using **consistent pseudonyms** while keeping every file usable and every
cross-file link intact.

Built for the Machina CAD De-ID track of the Builders Buildathon (Nov 2026).
Licensed under MIT.

## Approach

1. **Harvest** candidate identities (people, companies, accounts, emails,
   domains, project and part names) from every metadata field and path.
2. **Registry**: one global `original -> pseudonym` map. The same identity
   always gets the same pseudonym, and different identities stay distinct.
3. **Rewrite** each format with a dedicated handler. Text formats are
   re-serialized correctly. Binary formats use same-byte-length pseudonyms
   so offsets never shift.
4. **Validate** every output against its input. If a rewrite breaks a file,
   fall back to a conservative mode, then to the original bytes.
5. **Leak scan**: search the output (raw, UTF-16, inflated streams, archive
   members) for any original identifier.

File and folder names go through the same registry, and references between
files are rewritten together with the renames.

## Layout

See `deid/` for the pipeline, `tests/` for unit tests, `docs/attempts.md` for
the experiment log.

## Setup

```
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'
pytest
```
