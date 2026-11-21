"""Pass 2: write the de-identified corpus.

For every input file: map its path, rewrite its bytes with the handler for its
format, validate the result, and fall back to the original bytes when a
rewrite cannot be validated. Unchanged files are hard-linked (no copy).
"""

from __future__ import annotations

import io
import zlib
import json
import re
import os
import sys
import zipfile
from multiprocessing import Pool
from pathlib import Path

from deid.harvest import ext_of, list_files
from deid.registry.pseudonym import Mapper

TEXT_EXT = {"step", "stp", "p21", "igs", "iges", "sat", "sab_txt", "dxf", "svg", "obj", "mtl", "wrl",
            "vrml", "x3d", "txt", "md", "csv", "tsv", "xml", "json", "html", "htm", "scad", "ini",
            "cfg", "yaml", "yml", "gcode", "nc", "ngc", "tex", "py", "kicad_pcb", "kicad_sch",
            "kicad_pro", "kicad_mod", "kicad_sym", "brd", "sch", "ply", "off", "amf", "urdf", "sdf",
            "xacro", "dae", "gltf", "rtf", "log", "bat", "sh", "js", "css", "ts", "lua", "m",
            "ipynb", "toml", "fcmacro", "fcmat", "readme", "license", "brep", "brp", "x_t", "xmt_txt"}
ZIP_EXT = {"fcstd", "3mf", "f3d", "docx", "xlsx", "pptx", "odt", "ods", "kmz", "zip", "f3z"}
ARCHIVE_EXT = {"zip"}
OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"

G: dict = {}  # per-worker globals


# ---------------------------------------------------------------- registry
def load_mappers(registry_path: str, secret: bytes) -> tuple[Mapper, Mapper]:
    from deid.registry.build import FORMAT_WORDS

    reg = json.loads(Path(registry_path).read_text())
    reg["identities"] = [r for r in reg["identities"] if r["value"].lower().strip() not in FORMAT_WORDS]
    allm, content = Mapper(secret=secret), Mapper(secret=secret)
    for r in reg["identities"]:
        allm.add(r["value"], r["kind"])
    from deid.registry.pseudonym import norm

    for r in reg["identities"]:
        k = norm(r["value"])
        if r["scope"] == "global" and k in allm.entries:
            content.entries[k] = allm.entries[k]
            content.kinds[k] = r["kind"]
    return allm, content


def path_mapper(content: Mapper) -> Mapper:
    """Mapper for file and folder names: no part/drawing numbers. Native CAD assemblies and
    drawings reference parts by file name inside streams we cannot rewrite (SolidWorks 2015+),
    so renaming part files breaks drawing/model links (attempt 5: 118 -> 2023 native renames,
    drawing/model 175 -> 154)."""
    pm = Mapper(secret=content.secret)
    for k, v in content.entries.items():
        if content.kinds.get(k) != "part":
            pm.entries[k] = v
            pm.kinds[k] = content.kinds.get(k)
    return pm


# ---------------------------------------------------------------- paths
_BM: dict = {}


def _basename_mapper(m: Mapper) -> Mapper:
    bm = _BM.get(id(m))
    if bm is None:
        bm = Mapper(secret=m.secret)
        for k, v in m.entries.items():
            if m.kinds.get(k) in ("person", "account", "email", "domain", "phone"):
                bm.entries[k] = v
                bm.kinds[k] = m.kinds.get(k)
        _BM[id(m)] = bm
    return bm


NATIVE_EXT = {"sldprt", "sldasm", "slddrw", "sldlfp", "slddrt", "ipt", "iam", "idw", "ipn", "par", "psm", "asm", "dft",
              "catpart", "catproduct", "catdrawing", "prt", "drw", "neu", "x_t", "x_b"}


def _stem_key(name: str) -> str:
    """Lower-case file stem without version suffix (part.prt.3 -> part)."""
    b = re.sub(r"\.\d+$", "", name.lower())
    return b.rpartition(".")[0] or b


def native_stems(files) -> frozenset:
    out = set()
    for f in files:
        b = re.sub(r"\.\d+$", "", f.rsplit("/", 1)[-1].lower())
        if b.rpartition(".")[2] in NATIVE_EXT:
            out.add(b.rpartition(".")[0])
    return frozenset(out)


_PM: dict = {}


def _part_mapper(m: Mapper) -> Mapper:
    pm = _PM.get(id(m))
    if pm is None:
        pm = Mapper(secret=m.secret)
        for k, v in m.entries.items():
            if m.kinds.get(k) == "part":
                pm.entries[k] = v
                pm.kinds[k] = "part"
        _PM[id(m)] = pm
    return pm


def map_path(rel: str, allm: Mapper, content: Mapper, rename: bool) -> str:
    if not rename:
        return rel
    parts = rel.split("/")
    out = []
    for i, seg in enumerate(parts):
        new = seg
        if i == 2 and parts[0] == "sources" and parts[1] in ("github", "gitlab"):
            bits = seg.split("__")
            new = "__".join(allm.pseudonym(b) if b and b.lower() in allm.entries and not
                            b.lower().startswith("gitlab.") else b for b in bits)
        elif i == 2 and parts[0] == "sources" and parts[1] in ("web", "catalog"):
            new = allm.pseudonym(seg) if seg.lower() in allm.entries else seg
        elif i == 1 and parts[0] == "archives":
            stem, dot, ext = seg.rpartition(".")
            bits = stem.split("__")
            new = "__".join(allm.pseudonym(b) if b.lower() in allm.entries else b for b in bits) + dot + ext
        if i == len(parts) - 1 and "." in new:
            stem, dot, ext = new.rpartition(".")
            # the extension is never renamed; file stems only take person/account/email/domain/phone renames:
            # native CAD files reference each other by file name inside streams we cannot always rewrite
            new_stem = _basename_mapper(content).replace_text(stem)
            # drawing <-> model correspondence: a part/drawing number used as a file stem is replaced in
            # the drawing text, so the file must carry the same pseudonym -- unless a native CAD file
            # shares the stem (native files reference each other by name inside streams we cannot rewrite)
            ns = G.get("native_stems")
            if ns is not None and G.get("content") is not None and _stem_key(seg) not in ns:
                new_stem = _part_mapper(G["content"]).replace_text(new_stem)
            new = new_stem + dot + ext
        else:
            new = content.replace_text(new)
        out.append(new)
    return "/".join(out)


# ---------------------------------------------------------------- handlers
def rw_text(data: bytes, m: Mapper) -> bytes:
    return m.replace_bytes(data, ("ascii",))


def _in_step_string(data: bytes, s: int, e: int) -> bool:
    """True if [s, e) lies inside a quoted literal or a /* comment */ of a STEP file."""
    win = max(0, s - 200_000)
    if data.rfind(b"/*", win, s) > data.rfind(b"*/", win, s):
        return True  # inside a (possibly multi-line) comment
    # strings may span lines (FILE_NAME paths); quotes inside strings are doubled (''), so parity
    # from the start of the statement is exact
    ls = data.rfind(b";", win, s) + 1 or win
    return data.count(b"'", ls, s) % 2 == 1


def rw_step(data: bytes, m: Mapper) -> bytes:
    return m.replace_bytes(data, ("ascii",), accept=_in_step_string)


def rw_stl(data: bytes, m: Mapper) -> bytes:
    if data[:5].lower() == b"solid" and b"facet" in data[:2000]:
        return rw_text(data, m)
    if len(data) >= 84:
        return m.replace_bytes(data[:80], ("ascii",)) + data[80:]
    return data


def rw_zip(data: bytes, m: Mapper, name_map=None, depth: int = 0) -> bytes:
    zin = zipfile.ZipFile(io.BytesIO(data))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zout:
        for info in zin.infolist():
            body = zin.read(info)
            new_name = name_map(info.filename) if name_map else info.filename
            new_body = rewrite_bytes(new_name, body, m, depth + 1) if not info.is_dir() else body
            ni = zipfile.ZipInfo(new_name, date_time=info.date_time)
            ni.compress_type = info.compress_type
            ni.external_attr = info.external_attr
            ni.create_system = info.create_system
            ni.comment = info.comment
            zout.writestr(ni, new_body)
        zout.comment = m.replace_bytes(zin.comment, ("ascii",)) if zin.comment else b""
    out = buf.getvalue()
    if zipfile.ZipFile(io.BytesIO(out)).testzip() is not None:
        raise ValueError("zip test failed")
    return out


def _pdf_render_warnings(data: bytes, max_pages: int = 4) -> int:
    """Count MuPDF warnings while opening and rendering the first pages at low resolution."""
    import fitz

    fitz.TOOLS.mupdf_display_errors(False)
    fitz.TOOLS.reset_mupdf_warnings()
    try:
        doc = fitz.open(stream=data, filetype="pdf")
        for i, page in enumerate(doc):
            if i >= max_pages:
                break
            page.get_text()
            page.get_pixmap(dpi=12)
    except Exception:
        return 10**6
    w = fitz.TOOLS.mupdf_warnings()
    return len(w.splitlines()) if w else 0


def rw_pdf(data: bytes, m: Mapper, streams: bool = True) -> bytes:
    import pikepdf

    pdf = pikepdf.open(io.BytesIO(data))
    n_pages = len(pdf.pages)
    changed = False

    def fix(obj, seen):
        nonlocal changed
        if isinstance(obj, pikepdf.String):
            raw = bytes(obj)
            new = m.replace_bytes(raw, ("ascii", "utf-16-be"))
            if new != raw:
                changed = True
                return pikepdf.String(new)
            return obj
        return obj

    def walk(obj, seen):
        nonlocal changed
        if isinstance(obj, (pikepdf.Dictionary, pikepdf.Stream)):
            og = obj.objgen
            if og != (0, 0):
                if og in seen:
                    return
                seen.add(og)
            for k in list(obj.keys()):
                v = obj[k]
                if isinstance(v, pikepdf.String):
                    nv = fix(v, seen)
                    if nv is not v:
                        obj[k] = nv
                else:
                    walk(v, seen)
            if streams and isinstance(obj, pikepdf.Stream):
                filt = obj.get("/Filter")
                filters = [str(f) for f in (filt if isinstance(filt, pikepdf.Array) else [filt] if filt else [])]
                is_font_or_image = (
                    "/Length1" in obj or "/Length2" in obj
                    or str(obj.get("/Subtype", "")) in ("/Image", "/Type1C", "/CIDFontType0C", "/OpenType")
                )
                if not is_font_or_image and not any(
                        f in ("/DCTDecode", "/JPXDecode", "/CCITTFaxDecode", "/JBIG2Decode") for f in filters):
                    try:
                        raw = obj.read_bytes()
                    except Exception:
                        return
                    new = m.replace_bytes(raw, ("ascii", "utf-16-be"))
                    if new != raw:
                        # write() expects data already encoded with `filter`: compress it ourselves
                        obj.write(zlib.compress(new), filter=pikepdf.Name.FlateDecode, decode_parms=None)
                        changed = True
        elif isinstance(obj, pikepdf.Array):
            for i, v in enumerate(obj):
                if isinstance(v, pikepdf.String):
                    nv = fix(v, seen)
                    if nv is not v:
                        obj[i] = nv
                else:
                    walk(v, seen)

    seen: set = set()
    walk(pdf.trailer, seen)
    for obj in pdf.objects:
        walk(obj, seen)
    if not changed:
        return _guarded(data, m)
    out = io.BytesIO()
    pdf.save(out, static_id=False, fix_metadata_version=False,
             stream_decode_level=pikepdf.StreamDecodeLevel.none, compress_streams=False,
             object_stream_mode=pikepdf.ObjectStreamMode.preserve)
    res = _guarded(out.getvalue(), m)
    if len(pikepdf.open(io.BytesIO(res)).pages) != n_pages:
        raise ValueError("page count changed")
    return res


def rw_ole(data: bytes, m: Mapper) -> bytes:
    """Same-length rewrite of every OLE stream, patched in place (mini-stream safe).

    Property-set streams (names starting with \x05) hold author / last-saved-by
    / company strings: full replacement. Other streams: only matches inside long
    plain-string runs, so compressed or binary payloads are never touched.
    """
    from deid.formats import ole_inplace

    local = _ole_field_mapper(data)

    def transform(name: str, body: bytes) -> bytes:
        body = _transform_main(name, body)
        if local is not None and not name.startswith("\x05"):
            # the file's own author / last-saved-by values also live in Header2, ISolidWorksInformation,
            # Contents/*, UFRxDoc ...: replace them there with the same pseudonym (word-bounded)
            body = local.replace_bytes(body, ("utf-16-le", "ascii"),
                                       accept=lambda src, a, b: b - a >= 4)
        return body

    def _transform_main(name: str, body: bytes) -> bytes:
        if name.startswith("\x05"):
            from deid.formats import oleps

            body = m.replace_bytes(body, ("ascii", "utf-16-le"))
            return oleps.rewrite_fields(body, G.get("allm") or m)
        # other streams: short length-prefixed strings (user names, paths) are
        # missed by run-guarding; a word-bounded match of a registered name of
        # >=5 bytes does not occur by chance in binary data
        return m.replace_bytes(body, ("ascii", "utf-16-le"), accept=lambda src, a, b: b - a >= 5)

    return ole_inplace.rewrite(data, transform)


PROP_WORDS = {"author", "owner", "user", "users", "title", "subject", "company", "manager", "description",
              "comments", "keywords", "category", "admin", "default", "unknown", "name", "designer", "engineer"}


def _propagate_ok(v: str, kind: str | None) -> bool:
    """Per-file propagation of field values into other streams/sections: people and accounts only,
    never property-name words, standards, licences or numbers."""
    from deid.formats.swx import field_ok

    return (kind in ("person", "account") and field_ok(v) and v.strip().lower() not in PROP_WORDS
            and not re.search(r"(?i)\biso\b|\bdin\b|licen|attribution|creative|terraform|\d{3}", v))


def _ole_field_mapper(data: bytes):
    """Mapper holding only this file's identity-field values (author, last saved by, ...),
    with the corpus-wide pseudonyms from the full registry."""
    import io

    import olefile

    from deid.formats import oleps
    from deid.registry.pseudonym import norm

    allm = G.get("allm")
    if allm is None:
        return None
    try:
        ole = olefile.OleFileIO(io.BytesIO(data))
    except Exception:
        return None
    lm = Mapper(secret=allm.secret)
    try:
        for e in ole.listdir(streams=True, storages=False):
            if not e[-1].startswith("\x05"):
                continue
            for fmtid, pid, v in oleps.parse(ole.openstream(e).read()):
                k = norm(v)
                if oleps._kind(fmtid, pid) and len(v) >= 3 and k in allm.entries and \
                        _propagate_ok(v, allm.kinds.get(k)):
                    lm.entries[k] = allm.entries[k]
                    lm.kinds[k] = allm.kinds.get(k, "account")
    finally:
        ole.close()
    return lm if lm.entries else None


def _guarded(body: bytes, m: Mapper) -> bytes:
    """Replace only matches sitting inside long printable runs (plain strings)."""
    import re

    if not m.entries:
        return body
    out = bytearray(body)
    hit = False
    for enc, rx in (("ascii", re.compile(rb"[\x20-\x7e]{8,}")),
                    ("utf-16-le", re.compile(rb"(?:[\x20-\x7e]\x00){8,}"))):
        for run in rx.finditer(body):
            seg = run.group(0)
            new = m.replace_bytes(seg, (enc,))
            if new != seg:
                out[run.start():run.end()] = new
                hit = True
    return bytes(out) if hit else body


def rewrite_bytes(name: str, data: bytes, m: Mapper, depth: int = 0) -> bytes:
    e = ext_of(name)
    head = data[:8]
    if not data:
        return data
    if e in ("step", "stp", "p21") or head.startswith(b"ISO-1030"):
        return rw_step(data, m)
    if e == "stl":
        return rw_stl(data, m)
    if head.startswith(b"%PDF") or e == "pdf":
        from deid.formats import pdftext

        orig = data
        try:
            data = pdftext.rewrite(data, m)
        except Exception:
            pass
        try:
            out = rw_pdf(data, m)
        except Exception:
            out = rw_pdf(data, m, streams=False)
        if out != orig and _pdf_render_warnings(out) > _pdf_render_warnings(orig):
            # something we touched no longer renders cleanly: keep the safest variant
            safe = rw_pdf(orig, m, streams=False)
            return safe if _pdf_render_warnings(safe) <= _pdf_render_warnings(orig) else orig
        return out
    if head.startswith(b"PK\x03\x04") and (e in ZIP_EXT) and depth < 4:
        if e in ARCHIVE_EXT and not G.get("archives", False):
            return data
        name_map = (lambda n: map_path(n, G["allm"], G.get("pathm", m), True)) if e in ARCHIVE_EXT else None
        return rw_zip(data, m, name_map, depth)
    if head.startswith(OLE_MAGIC):
        try:
            return rw_ole(data, m)
        except Exception:
            # olefile cannot rewrite mini-stream entries; same-length patch of
            # plain-string runs in the container keeps every sector offset valid
            out = _guarded(data, m)
            import olefile

            olefile.OleFileIO(io.BytesIO(out)).close()
            return out
    if e in ("sldprt", "sldasm", "slddrw", "sldlfp", "slddrt") and G.get("swx", False):
        from deid.formats import swx

        if swx.is_swx(data):
            return rw_swx(data, m)
    if e in TEXT_EXT or head.startswith(b"#UGC:") or _looks_text(data):
        return rw_text(data, m)
    return data


def rw_swx(data: bytes, m: Mapper) -> bytes:
    """SolidWorks 2015+ sections: XML property sections get full replacement; binary sections only
    word-bounded matches of >=5 bytes (as for OLE streams). Field values (creator, last saved by,
    drawn by ...) found in this file are replaced in every section with their corpus pseudonym."""
    from deid.formats import swx
    from deid.registry.pseudonym import norm

    allm = G.get("allm") or m
    local = Mapper(secret=allm.secret)
    for v, k in swx.harvest(data):
        key = norm(v)
        if len(v) >= 3 and key in allm.entries and _propagate_ok(v, allm.kinds.get(key)):
            local.entries[key] = allm.entries[key]
            local.kinds[key] = allm.kinds.get(key, "account")

    def transform(name: str, body: bytes) -> bytes:
        if name.endswith((".xml", ".rels")) or name.startswith("docProps/"):
            body = m.replace_bytes(body, ("ascii",))
            if local.entries:
                body = local.replace_bytes(body, ("ascii",))
            return body
        body = m.replace_bytes(body, ("ascii", "utf-16-le"), accept=lambda src, a, b: b - a >= 5)
        if local.entries:
            body = local.replace_bytes(body, ("utf-16-le", "ascii"), accept=lambda src, a, b: b - a >= 4)
        return body

    return swx.rewrite(data, transform)


def _looks_text(data: bytes) -> bool:
    sample = data[:8192]
    if b"\x00" in sample:
        return False
    printable = sum(1 for c in sample if 32 <= c < 127 or c in (9, 10, 13))
    return printable >= 0.95 * len(sample)


# ---------------------------------------------------------------- driver
def _init(registry_path: str, secret: bytes, opts: dict) -> None:
    G["allm"], G["content"] = load_mappers(registry_path, secret)
    G["pathm"] = path_mapper(G["content"])
    G.update(opts)


def process(args: tuple[str, str, str]) -> tuple[str, str, str]:
    root, out_root, rel = args
    src = os.path.join(root, rel)
    new_rel = map_path(rel, G["allm"], G["pathm"], G.get("rename", False))
    dst = os.path.join(out_root, new_rel)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    status = "same"
    try:
        size = os.path.getsize(src)
        if size == 0 or size > 1_500_000_000:
            raise _Same()
        with open(src, "rb") as f:
            data = f.read()
        new = rewrite_bytes(rel, data, G["content"])
        if new == data:
            raise _Same()
        with open(dst, "wb") as f:
            f.write(new)
        status = "changed"
    except _Same:
        _link(src, dst)
    except Exception as ex:  # noqa: BLE001 - validation failure: keep original bytes
        _link(src, dst)
        status = f"fallback:{type(ex).__name__}"
    return rel, new_rel, status


class _Same(Exception):
    pass


def _link(src: str, dst: str) -> None:
    if os.path.exists(dst):
        os.remove(dst)
    try:
        os.link(src, dst)
    except OSError:
        import shutil

        shutil.copy2(src, dst)


def run(root: str, out_root: str, registry_path: str, secret: bytes, opts: dict, workers=None) -> None:
    files = list_files(root)
    print(f"rewriting {len(files)} files -> {out_root} opts={opts}", file=sys.stderr)
    if opts.get("part_stems", True) and opts.get("rename"):
        opts = dict(opts, native_stems=native_stems(files))
    results = []
    with Pool(workers or os.cpu_count(), initializer=_init, initargs=(registry_path, secret, opts)) as pool:
        for i, r in enumerate(pool.imap_unordered(process, [(root, out_root, f) for f in files], chunksize=16)):
            results.append(r)
            if i % 10000 == 0:
                print(f"  {i}", file=sys.stderr)
    seen: dict[str, str] = {}
    for rel, new_rel, _ in results:
        if new_rel in seen and seen[new_rel] != rel:
            print(f"PATH COLLISION {new_rel}", file=sys.stderr)
        seen[new_rel] = rel
    Path(out_root).parent.joinpath("rewrite-results.json").write_text(json.dumps(results))
    from collections import Counter

    print(Counter(s.split(":")[0] for _, _, s in results), file=sys.stderr)
    print(Counter(s for _, _, s in results if s.startswith("fallback")).most_common(10), file=sys.stderr)
