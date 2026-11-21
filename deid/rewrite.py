"""Pass 2: write the de-identified corpus.

For every input file: map its path, rewrite its bytes with the handler for its
format, validate the result, and fall back to the original bytes when a
rewrite cannot be validated. Unchanged files are hard-linked (no copy).
"""

from __future__ import annotations

import io
import json
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
    reg = json.loads(Path(registry_path).read_text())
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


# ---------------------------------------------------------------- paths
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
    ls = max(data.rfind(b";", 0, s), data.rfind(b"\n", 0, s)) + 1
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
                if not any(f in ("/DCTDecode", "/JPXDecode", "/CCITTFaxDecode", "/JBIG2Decode") for f in filters):
                    try:
                        raw = obj.read_bytes()
                    except Exception:
                        return
                    new = m.replace_bytes(raw, ("ascii", "utf-16-be"))
                    if new != raw:
                        obj.write(new, filter=pikepdf.Name.FlateDecode)
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
    import olefile

    bio = io.BytesIO(data)
    ole = olefile.OleFileIO(bio, write_mode=True)
    changed = False
    for entry in ole.listdir(streams=True, storages=False):
        try:
            if ole.get_size(entry) > 8_000_000:
                continue
            body = ole.openstream(entry).read()
        except Exception:
            continue
        is_props = entry[-1].startswith("\x05")
        new = m.replace_bytes(body, ("ascii", "utf-16-le")) if is_props else _guarded(body, m)
        if new != body and len(new) == len(body):
            ole.write_stream(entry, new)
            changed = True
    ole.close()
    if not changed:
        return data
    res = bio.getvalue()
    olefile.OleFileIO(io.BytesIO(res)).close()
    return res


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
        try:
            return rw_pdf(data, m)
        except Exception:
            return rw_pdf(data, m, streams=False)
    if head.startswith(b"PK\x03\x04") and (e in ZIP_EXT) and depth < 4:
        if e in ARCHIVE_EXT and not G.get("archives", False):
            return data
        name_map = (lambda n: map_path(n, G["allm"], m, True)) if e in ARCHIVE_EXT else None
        return rw_zip(data, m, name_map, depth)
    if head.startswith(OLE_MAGIC):
        try:
            return rw_ole(data, m)
        except NotImplementedError:
            # olefile cannot rewrite mini-stream entries; same-length patch of
            # plain-string runs in the container keeps every sector offset valid
            out = _guarded(data, m)
            import olefile

            olefile.OleFileIO(io.BytesIO(out)).close()
            return out
    if e in TEXT_EXT or head.startswith(b"#UGC:") or _looks_text(data):
        return rw_text(data, m)
    return data


def _looks_text(data: bytes) -> bool:
    sample = data[:8192]
    if b"\x00" in sample:
        return False
    printable = sum(1 for c in sample if 32 <= c < 127 or c in (9, 10, 13))
    return printable >= 0.95 * len(sample)


# ---------------------------------------------------------------- driver
def _init(registry_path: str, secret: bytes, opts: dict) -> None:
    G["allm"], G["content"] = load_mappers(registry_path, secret)
    G.update(opts)


def process(args: tuple[str, str, str]) -> tuple[str, str, str]:
    root, out_root, rel = args
    src = os.path.join(root, rel)
    new_rel = map_path(rel, G["allm"], G["content"], G.get("rename", False))
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
