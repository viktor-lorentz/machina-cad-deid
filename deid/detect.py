"""Registry-independent leak detection (agent B).

The registry-based leak scan can only find identities the harvest already knows.
These detectors look for identity *shapes* instead, so harvest misses show up:

* patterns: e-mail addresses, URL hosts, absolute-path user names
  (C:\\Users\\x, /home/x, /Users/x), DOMAIN\\user accounts, phone numbers;
* fields: metadata slots that hold an identity by definition (PDF /Author and
  XMP dc:creator, STEP FILE_NAME author/organization, PERSON, ORGANIZATION,
  IGES global author/organization, FCStd CreatedBy/Company/LastModifiedBy,
  3MF Designer/DesignerUserId, OLE SummaryInformation author/last saver/company).

A finding is "explained" (not a leak) when it is empty, a generic placeholder,
on the allowlist of non-identifying hosts, or made only of pseudonym material
(every alphanumeric token is a token of some pseudonym the registry produced).

Containers are opened recursively: zip (incl. FCStd/3MF), gzip, tar, OLE
streams, zlib streams inside binaries (SolidWorks), and PDF streams/strings.
"""

from __future__ import annotations

import gzip
import io
import re
import tarfile
import zipfile
import zlib
from collections import Counter

# ---------------------------------------------------------------- patterns
EMAIL = re.compile(rb"[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9-]{1,63}(?:\.[A-Za-z0-9-]{1,63})*\.[A-Za-z]{2,24}")
URLHOST = re.compile(rb"(?i)\b(?:https?|ftp)://([A-Za-z0-9.-]{3,253})")
WINUSER = re.compile(rb"(?i)[A-Z]:[\\/]{1,2}(?:Users|Documents and Settings)[\\/]{1,2}([^\\/\"'<>|:*?\x00\r\n]{1,64})")
UNIXUSER = re.compile(rb"/(?:home|Users)/([A-Za-z0-9._-]{2,64})")
DOMUSER = re.compile(rb"(?<![A-Za-z0-9\\])([A-Z][A-Z0-9-]{2,15})\\([A-Za-z][A-Za-z0-9._-]{2,30})(?![A-Za-z0-9\\])")
PHONE = re.compile(rb"(?<![\d.])(?:\+\d{1,3}[ .-]?)?(?:\(\d{3}\) ?\d{3}([.-])|\d{3}([.-])\d{3}\2)\d{4}(?![\d.])")

# Hosts, users and values that never identify anyone.
ALLOW_HOSTS = {
    "www.w3.org", "w3.org", "purl.org", "ns.adobe.com", "www.iso.org", "iso.org", "schemas.openxmlformats.org",
    "schemas.microsoft.com", "example.com", "www.example.com", "localhost", "127.0.0.1", "xmlns.com",
    "www.opengis.net", "creativecommons.org", "www.gnu.org", "gnu.org", "opensource.org", "www.inkscape.org",
    "inkscape.org", "sodipodi.sourceforge.net", "www.freecadweb.org", "www.freecad.org", "freecad.org",
    "schemas.microsoft.com", "www.adobe.com", "uri.etsi.org", "ns.useplus.org", "iptc.org", "www.aiim.org",
}
ALLOW_USERS = {"public", "default", "shared", "all users", "administrator", "admin", "user", "username", "guest",
               "runner", "root", "build", "travis", "appveyor", "vagrant", "ubuntu", "docker"}
GENERIC = {"admin", "administrator", "user", "users", "owner", "sysadmin", "windows", "microsoft", "solidworks",
           "open", "cascade", "opencascade", "autodesk", "ptc", "siemens", "dassault", "systemes", "unknown",
           "organisation", "organization", "company", "author", "default", "guest", "pc", "desktop", "laptop"}
PUBLIC_HOSTS = ("wikipedia.org", "microsoft.com", "adobe.com", "autodesk.com", "solidworks.com", "ptc.com", "iec.ch",
                "iso.org", "github.com", "google.com", "youtube.com", "digicert.com", "verisign.com", "globalsign.com",
                "symantec.com", "netfabb.com", "openscad.org", "freecad.org", "freecadweb.org", "kicad.org",
                "onshape.com", "mcmaster.com", "thingiverse.com", "grabcad.com", "apple.com", "mozilla.org",
                "w3.org", "adobe.io", "python.org", "sourceforge.net", "ietf.org", "unicode.org", "openxmlformats.org")
PLACEHOLDERS = {"", "unknown", "none", "n/a", "na", "null", "author", "user", "owner", "anonymous", "organization",
                "organisation", "company", "-", "?", "undefined", "default", "unspecified", "not specified"}

_TOK = re.compile(r"[a-z0-9]+")


class Explainer:
    """Decides whether a found string is made of pseudonym material."""

    def __init__(self, pseudonyms=(), originals=()):
        self.pseudo = {p.lower() for p in pseudonyms}
        self.tokens = {t for p in self.pseudo for t in _TOK.findall(p) if len(t) >= 2}
        self.originals = {o.lower() for o in originals}

    def explained(self, value: str) -> bool:
        v = value.strip().lower()
        if v in PLACEHOLDERS or v in self.pseudo or not re.search(r"[a-z]", v):
            return True
        toks = [t for t in _TOK.findall(v) if not t.isdigit()]
        return all(t in self.tokens or t in GENERIC for t in toks)


def _dec(b: bytes) -> str:
    return b.decode("utf-8", "replace")


def scan_patterns(data: bytes, ex: Explainer, out: Counter, samples: dict) -> None:
    """Pattern detectors over raw bytes, plus a UTF-16LE view when the data has many NULs."""
    sample = data[:65536]
    binary = sum(b < 9 or 13 < b < 32 or b == 127 for b in sample) > len(sample) // 20
    # in binary data, only look inside printable runs (like `strings`), never across random bytes
    views = [b"\n".join(re.findall(rb"[\x20-\x7e]{8,}", data))] if binary else [data]
    if data.count(b"\x00") > len(data) // 8:
        try:
            views.append(data.decode("utf-16-le", "ignore").encode("utf-8", "ignore"))
        except Exception:
            pass
    for v in views:
        for m in EMAIL.finditer(v):
            s = _dec(m.group(0))
            host = s.rsplit("@", 1)[1].lower()
            tld = s.rsplit(".", 1)[-1]
            if host in ALLOW_HOSTS or ex.explained(s) or not (tld.islower() or tld in ("com", "org", "net", "edu")) \
                    or min(len(x) for x in host.split(".")) < 2:
                continue
            _hit(out, samples, "email", s)
        for m in URLHOST.finditer(v):
            h = _dec(m.group(1)).lower().rstrip(".")
            if h in ALLOW_HOSTS or any(h == p or h.endswith("." + p) for p in PUBLIC_HOSTS) or ex.explained(h):
                continue
            _hit(out, samples, "url-host", h)
        for rx, kind in ((WINUSER, "path-user"), (UNIXUSER, "path-user")):
            for m in rx.finditer(v):
                u = _dec(m.group(1)).strip()
                if u.lower() in ALLOW_USERS or ex.explained(u):
                    continue
                _hit(out, samples, kind, u)
        for m in DOMUSER.finditer(v):
            u = _dec(m.group(2))
            if u.lower() in ALLOW_USERS or ex.explained(u):
                continue
            _hit(out, samples, "domain-account", _dec(m.group(0)))
        for m in PHONE.finditer(v):
            _hit(out, samples, "phone", _dec(m.group(0)))


def _hit(out: Counter, samples: dict, kind: str, value: str) -> None:
    out[kind] += 1
    s = samples.setdefault(kind, [])
    if len(s) < 5 and value not in s:
        s.append(value)


# ---------------------------------------------------------------- fields
_STEP_STR = rb"'((?:[^']|'')*)'"
STEP_FILE_NAME = re.compile(rb"FILE_NAME\s*\(\s*" + _STEP_STR + rb"\s*,\s*" + _STEP_STR + rb"\s*,\s*\(([^)]*)\)\s*,\s*\(([^)]*)\)", re.S)
STEP_PERSON = re.compile(rb"=\s*PERSON\s*\(\s*" + _STEP_STR + rb"\s*,\s*" + _STEP_STR + rb"\s*,\s*" + _STEP_STR)
STEP_ORG = re.compile(rb"=\s*ORGANIZATION\s*\(\s*" + _STEP_STR + rb"\s*,\s*" + _STEP_STR)
XML_PROP = re.compile(rb'<Property\s+name="(CreatedBy|Company|LastModifiedBy)"[^>]*>\s*<String\s+value="([^"]*)"', re.S)
TMF_META = re.compile(rb'<metadata\s+name="(Designer|DesignerUserId|Copyright|LicenseTerms)"[^>]*>([^<]*)</metadata>', re.S)
XMP_CREATOR = re.compile(rb"<dc:creator>.*?<rdf:li[^>]*>([^<]*)</rdf:li>", re.S)


def _field(out: Counter, samples: dict, ex: Explainer, kind: str, value: str) -> None:
    value = value.strip()
    if value and not ex.explained(value):
        _hit(out, samples, "field:" + kind, value)


def scan_fields(data: bytes, ext: str, ex: Explainer, out: Counter, samples: dict) -> None:
    if data.startswith(b"ISO-10303-21"):
        head = data[:20000]
        m = STEP_FILE_NAME.search(head)
        if m:
            for grp, kind in ((3, "step-author"), (4, "step-org")):
                for s in re.findall(_STEP_STR, m.group(grp)):
                    _field(out, samples, ex, kind, _dec(s))
        for m in STEP_PERSON.finditer(data):
            for s in (m.group(2), m.group(3)):
                if s not in (b"", b"$"):
                    _field(out, samples, ex, "step-person", _dec(s))
        for m in STEP_ORG.finditer(data):
            _field(out, samples, ex, "step-org", _dec(m.group(2)))
    if ext in ("igs", "iges") or re.match(rb"S[ 0-9]{7}\r?\n", data[72:82]):
        _iges_global(data, ex, out, samples)
    for m in XML_PROP.finditer(data):
        _field(out, samples, ex, "fcstd-" + _dec(m.group(1)), _dec(m.group(2)))
    for m in TMF_META.finditer(data):
        if m.group(1) in (b"Designer", b"DesignerUserId"):
            _field(out, samples, ex, "3mf-" + _dec(m.group(1)), _dec(m.group(2)))
    for m in XMP_CREATOR.finditer(data):
        _field(out, samples, ex, "xmp-creator", _dec(m.group(1)))


def _iges_global(data: bytes, ex: Explainer, out: Counter, samples: dict) -> None:
    g = b"".join(line[:72] for line in data.splitlines() if line[72:73] == b"G")
    if not g:
        return
    delim = b","
    if g[:2] == b"1H":
        delim = g[2:3]
    # Parse fields in order; global fields 21 and 22 (1-based) are author and organization.
    fields, i = [], 0
    while i < len(g) and len(fields) < 23:
        m = re.match(rb"\s*(\d+)H", g[i:])
        if m:
            n = int(m.group(1))
            start = i + m.end()
            fields.append(g[start:start + n])
            i = start + n
        else:
            j = g.find(delim, i)
            if j < 0:
                fields.append(g[i:].strip())
                break
            fields.append(g[i:j].strip())
            i = j
        if i < len(g) and g[i:i + 1] in (delim, b";"):
            i += 1
    for idx, kind in ((20, "iges-author"), (21, "iges-org")):
        if idx < len(fields):
            _field(out, samples, ex, kind, _dec(fields[idx]))


def scan_ole_meta(data: bytes, ex: Explainer, out: Counter, samples: dict) -> list[bytes]:
    """OLE property sets as fields; returns raw stream bytes for further scanning."""
    import olefile

    streams = []
    try:
        o = olefile.OleFileIO(io.BytesIO(data))
    except Exception:
        return streams
    try:
        md = o.get_metadata()
        for attr in ("author", "last_saved_by", "company", "manager"):
            v = getattr(md, attr, None)
            if isinstance(v, bytes):
                v = v.split(b"\x00", 1)[0]
            elif isinstance(v, str):
                v = v.split("\x00", 1)[0]
            if v:
                _field(out, samples, ex, "ole-" + attr, v.decode("latin-1", "replace") if isinstance(v, bytes) else str(v))
        for path in o.listdir(streams=True, storages=False):
            try:
                if o.get_size(path) < 50_000_000:
                    streams.append(o.openstream(path).read())
            except Exception:
                pass
    finally:
        o.close()
    return streams


# ---------------------------------------------------------------- containers
def zlib_streams(data: bytes, limit: int = 400) -> list[bytes]:
    """Decompress zlib streams found inside binary data (e.g. SolidWorks sections)."""
    found, tried, i = [], 0, 0
    while tried < limit:
        i = data.find(b"\x78", i)
        if i < 0 or i + 2 > len(data):
            break
        if data[i + 1] in (0x01, 0x5E, 0x9C, 0xDA) and ((data[i] << 8) | data[i + 1]) % 31 == 0:
            tried += 1
            try:
                d = zlib.decompressobj()
                raw = d.decompress(data[i:i + 64_000_000], 200_000_000)
                if len(raw) > 16:
                    found.append(raw)
                    i += max(2, len(data[i:]) - len(d.unused_data))
                    continue
            except zlib.error:
                pass
        i += 1
    return found


def children(name: str, data: bytes, depth: int) -> list[tuple[str, bytes]]:
    """Members of a container (name, bytes); empty for leaf data."""
    if depth > 4:
        return []
    out = []
    try:
        if data[:4] == b"PK\x03\x04":
            z = zipfile.ZipFile(io.BytesIO(data))
            for info in z.infolist():
                if not info.is_dir() and info.file_size < 300_000_000:
                    out.append((info.filename, z.read(info)))
        elif data[:2] == b"\x1f\x8b":
            out.append((name[:-3] if name.endswith(".gz") else name + "~", gzip.decompress(data)))
        elif len(data) > 262 and data[257:262] == b"ustar":
            t = tarfile.open(fileobj=io.BytesIO(data))
            for m in t.getmembers():
                if m.isfile() and m.size < 300_000_000:
                    f = t.extractfile(m)
                    if f:
                        out.append((m.name, f.read()))
    except Exception:
        pass
    return out


def pdf_parts(data: bytes) -> tuple[list[bytes], list[str]]:
    """Decoded streams and all string objects of a PDF."""
    import pikepdf

    streams, strings = [], []
    try:
        pdf = pikepdf.open(io.BytesIO(data))
    except Exception:
        return streams, strings
    for k, v in (pdf.docinfo or {}).items():
        try:
            strings.append(f"{k}={v}")
        except Exception:
            pass
    for obj in pdf.objects:
        try:
            if isinstance(obj, pikepdf.Stream):
                streams.append(obj.read_bytes())
            if isinstance(obj, (pikepdf.Dictionary, pikepdf.Stream)):
                for _, v in obj.items():
                    if isinstance(v, pikepdf.String):
                        strings.append(str(v))
            elif isinstance(obj, pikepdf.Array):
                for v in obj:
                    if isinstance(v, pikepdf.String):
                        strings.append(str(v))
        except Exception:
            pass
    return streams, strings


def scan_blob(name: str, data: bytes, ex: Explainer, out: Counter, samples: dict, depth: int = 0) -> None:
    """Full recursive scan of one file's bytes."""
    ext = name.rsplit(".", 1)[-1].lower() if "." in name.rsplit("/", 1)[-1] else ""
    scan_patterns(name.encode("utf-8", "replace"), ex, out, samples)
    scan_patterns(data, ex, out, samples)
    scan_fields(data, ext, ex, out, samples)
    if data[:4] == b"%PDF":
        streams, strings = pdf_parts(data)
        for s in streams:
            scan_patterns(s, ex, out, samples)
            scan_fields(s, "", ex, out, samples)
        for s in strings:
            b = s.encode("utf-8", "replace")
            scan_patterns(b, ex, out, samples)
            if s.startswith("/Author="):
                _field(out, samples, ex, "pdf-author", s[len("/Author="):])
        return
    if data[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        for s in scan_ole_meta(data, ex, out, samples):
            scan_patterns(s, ex, out, samples)
        return
    kids = children(name, data, depth)
    for cname, cdata in kids:
        scan_blob(name + "!" + cname, cdata, ex, out, samples, depth + 1)
    if not kids and ext in ("sldprt", "sldasm", "slddrw", "ipt", "iam", "idw", "par", "psm", "asm", "f3d", "dwg"):
        for s in zlib_streams(data):
            scan_patterns(s, ex, out, samples)
            scan_fields(s, "", ex, out, samples)
