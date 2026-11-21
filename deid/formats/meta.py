"""Metadata harvesters for non-STEP formats.

Each function takes raw bytes and returns (value, kind) candidates taken from
fields whose meaning is an identity (author, company, designer, ...).
"""

from __future__ import annotations

import io
import re
import zipfile

_XML_FIELD = re.compile(
    rb"<(?:dc:creator|cp:lastModifiedBy|dc:publisher|pdf:Author|xmp:Author|meta:initial-creator|"
    rb"meta:creator|Author|Company|Manager)[^>]*>\s*(?:<rdf:Seq>\s*<rdf:li[^>]*>)?([^<]{2,120})<",
    re.I,
)
# FreeCAD Document.xml: <Property name="CreatedBy" type="App::PropertyString"><String value="..."/>
_FC_PROP = re.compile(
    rb'<Property name="(CreatedBy|LastModifiedBy|Company)"[^>]*>\s*'
    rb'<(?:String|Map)[^>]*value="([^"]{2,200})"',
)
# 3MF <metadata name="Designer">...</metadata>
_3MF_META = re.compile(
    rb'<metadata\s+name="(Designer|DesignerUserId|DesignerCover|Copyright|LicenseTerms|Title|'
    rb'Description|ProfileUserId|ProfileTitle|CreationUser|Origin)"[^>]*>([^<]{2,200})<',
    re.I,
)
_PDF_INFO = re.compile(rb"/(Author|Creator|Producer|Title|Subject|Keywords|Company)\s*\(((?:[^()\\]|\\.){1,200})\)")
_SOFTWARE = re.compile(
    r"solidworks|autodesk|inventor|acrobat|adobe|microsoft|word|excel|pdf|freecad|cairo|inkscape|"
    r"ghostscript|libreoffice|openoffice|skia|chrom|quartz|mac os|windows|draftsight|nanocad|"
    r"creo|pro/engineer|catia|fusion|onshape|kicad|prusa|bambu|cura|orca|slic3r|matplotlib|reportlab|"
    r"itext|qt |pdftex|latex|tex|dvips|aspose|bullzip|cutepdf|primopdf|pdfcreator|wkhtml|gpl|"
    r"edrawings|designspark|solid edge|siemens|sketchup|blender|openscad|rhino|ezdxf|librecad|"
    r"untitled|drawing|sheet|hoja|blatt|feuille|^part|^assembly|^model",
    re.I,
)


def _d(b: bytes) -> str:
    return b.decode("utf-8", "replace").strip()


def _ok(s: str) -> bool:
    return 2 < len(s) <= 120 and not re.fullmatch(r"[\d\W_]+", s)


def pdf(data: bytes) -> list[tuple[str, str]]:
    out = []
    for k, v in _PDF_INFO.findall(data):
        s = _d(v).replace("\\(", "(").replace("\\)", ")").replace("\\\\", "\\")
        if k in (b"Author", b"Company") and _ok(s):
            out.append((s, "person" if k == b"Author" else "company"))
    for v in _XML_FIELD.findall(data):
        s = _d(v)
        if _ok(s) and not _SOFTWARE.search(s):
            out.append((s, "person"))
    return out


def iges(data: bytes) -> list[tuple[str, str]]:
    """IGES global section: field 21 author, field 22 organization."""
    g = b"".join(line[:72] for line in data[:40000].splitlines() if len(line) >= 73 and line[72:73] == b"G")
    if not g:
        return []
    fields: list[bytes] = []
    i, n = 0, len(g)
    pdelim, rdelim = b",", b";"
    while i < n and len(fields) < 26:
        m = re.match(rb"\s*(\d+)H", g[i:])
        if m:
            ln = int(m.group(1))
            start = i + m.end()
            fields.append(g[start:start + ln])
            i = start + ln
        else:
            j = i
            while j < n and g[j:j + 1] not in (pdelim, rdelim):
                j += 1
            fields.append(g[i:j].strip())
            i = j
        if i < n and g[i:i + 1] == rdelim:
            break
        i += 1
    out = []
    for idx, kind in ((20, "person"), (21, "company")):
        if idx < len(fields):
            s = _d(fields[idx])
            if _ok(s) and not _SOFTWARE.search(s):
                out.append((s, kind))
    return out


def zipxml(data: bytes) -> list[tuple[str, str]]:
    out = []
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except Exception:
        return out
    for info in z.infolist()[:200]:
        name = info.filename
        if not name.lower().endswith((".xml", ".model", ".rels", ".json", ".config")) or info.file_size > 50_000_000:
            continue
        try:
            body = z.read(info)
        except Exception:
            continue
        for k, v in _FC_PROP.findall(body):
            s = _d(v)
            if _ok(s) and not _SOFTWARE.search(s):
                out.append((s, "company" if k == b"Company" else "person"))
        for k, v in _3MF_META.findall(body):
            s = _d(v)
            if k.lower() in (b"designer", b"designeruserid", b"profileuserid", b"creationuser") and _ok(s):
                out.append((s, "account" if b"Id" in k else "person"))
        for v in _XML_FIELD.findall(body):
            s = _d(v)
            if _ok(s) and not _SOFTWARE.search(s):
                out.append((s, "person"))
    return out


def ole(data: bytes) -> list[tuple[str, str]]:
    out = []
    try:
        import olefile

        o = olefile.OleFileIO(io.BytesIO(data))
        md = o.get_metadata()
        for attr, kind in (("author", "person"), ("last_saved_by", "person"), ("company", "company"),
                           ("manager", "person")):
            v = getattr(md, attr, None)
            if isinstance(v, bytes):
                s = v.decode("latin-1", "replace").strip("\x00 ").strip()
                if _ok(s) and not _SOFTWARE.search(s):
                    out.append((s, kind))
        o.close()
    except Exception:
        pass
    return out


def dxf(data: bytes) -> list[tuple[str, str]]:
    m = re.search(rb"\$LASTSAVEDBY\s*\r?\n\s*1\s*\r?\n([^\r\n]{2,80})", data[:200000])
    if m:
        s = _d(m.group(1))
        if _ok(s):
            return [(s, "account")]
    return []


def creo(data: bytes) -> list[tuple[str, str]]:
    out = []
    for m in re.finditer(rb"#- (HOST|DBID) +([^\s\\]{2,60})", data[:4000]):
        s = _d(m.group(2))
        if _ok(s):
            out.append((s, "account"))
    return out
