"""Turn harvested candidates into the identity registry.

Each identity gets a scope:
* "global": replaced everywhere (file contents, names, archive members);
* "path":   replaced only where it appears as a structural path segment
            (e.g. a repository name that is also a common word).
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

# Software, vendors, formats, standards and placeholders: never identities.
STOP = {
    "unspecified", "unknown", "none", "null", "default", "user", "admin", "administrator", "owner",
    "author", "designer", "company", "anonymous", "n/a", "na", "tbd", "test", "draft", "sample",
    "solidworks", "autodesk", "inventor", "freecad", "fusion", "fusion 360", "onshape", "creo",
    "catia", "siemens", "spatial", "spatial corp", "acis", "parasolid", "opencascade",
    "open cascade", "kicad", "openscad", "blender", "rhino", "sketchup", "prusa", "bambu lab",
    "bambulab", "cura", "ultimaker", "adobe", "microsoft", "windows", "linux", "github", "gitlab",
    "step", "iges", "stl", "pdf", "dxf", "dwg", "cad", "3d", "iso", "din", "ansi", "astm", "jis",
    "metric", "imperial", "drawing", "part", "assembly", "model", "sheet", "all rights reserved",
    "public domain", "creative commons", "cc-by", "mit", "gpl", "cern", "ohl", "master", "main",
    "release", "releases", "files", "cad-files", "hardware", "mechanical", "mechanics", "design",
    "designs", "project", "projects", "parts", "models", "drawings", "docs", "documentation",
    "source", "src", "export", "exports", "stl files", "step files", "pro", "lite", "mini", "v1",
    "v2", "v3", "robot", "robotics", "printer", "3d-printer", "library", "examples", "example",
    "dassault", "dassault systemes", "ptc", "pro/engineer", "nx", "solid edge", "draftsight",
    "librecad", "ezdxf", "inkscape", "gnu.org", "www.gnu.org",
}
MAIL_PROVIDERS = {"gmail.com", "googlemail.com", "outlook.com", "hotmail.com", "yahoo.com",
                  "icloud.com", "me.com", "live.com", "msn.com", "aol.com", "protonmail.com",
                  "proton.me", "gmx.de", "gmx.net", "web.de", "qq.com", "163.com", "mail.ru",
                  "yandex.ru", "users.noreply.github.com", "noreply.github.com"}


TLDS = set("""com org net edu gov mil int io co uk de fr it es ch nl be at se no dk fi pl cz sk hu ro
bg gr pt ie is ee lv lt si hr rs ua by ru kz tr il cn jp kr tw hk sg in id my th vn ph au nz ca us mx br
ar cl pe za eg info biz me dev ai tech xyz parts eu app cloud site online space store shop design
engineering tools works systems science lab academy""".split())
PLACEHOLDER = re.compile(r"^(?:NAUO|PERSON|ORGANIZATION|ORG|PER|PDF|SDR|PROD|PD)[-_]|_(?:NAME|ID|DESCRIPTION)$", re.I)
VENDOR = re.compile(r"kicad|stepup|ksu mcad|zwcad|step tools|steptools|3ds\.com|netfabb|matplotlib|cairograph|"
                    r"fontawesome|openstreetmap|osm\.org|naturalearth|protomaps|pdf-tools|aiim\.org|iec\.ch|"
                    r"solidworks|autodesk|dassault|siemens|ptc\.com|spatial|adobe|microsoft|freecad|onshape|"
                    r"opencascade|ugs|parasolid|acis|inventor|catia|creo|zwsoft|gstarcad|bricscad|draftsight|"
                    r"ghostscript|libreoffice|openoffice|inkscape|blender|sketchup|rhino|prusa|bambu|cura|^ns\.|useplus|color\.org|"
                    r"iptc\.org|npes\.org|gimp\.org|ilovepdf|hsmworks|episerver|w3\.org|adobe\.com|purl\.org|"
                    r"^(?:first|last|full|user|company|organi[sz]ation|author|designer) ?name$|^no ?name$|^a company$|"
                    r"^unknown|terraform|^ip[\d.]+$|^[0-9a-f]{20,}$|firma gmbh|^your |^my ", re.I)


def clean(v: str) -> str:
    v = v.replace("\x00", "")
    v = "".join(ch for ch in v if ch.isprintable() and ch != "\ufffd")
    return v.strip("﻿￾\xfe\xff \t")


def valid_host(h: str) -> bool:
    labels = h.split(".")
    return (len(labels) >= 2 and labels[-1].lower() in TLDS and labels[-1].isalpha()
            and all(re.fullmatch(r"[A-Za-z0-9-]{1,63}", x) for x in labels) and any(c.isalpha() for c in labels[-2]))


def _from_path(row: dict) -> bool:
    """True when the candidate is a structural path segment of its examples."""
    v = row["value"]
    return any(f"/{v}__" in "/" + ex or f"__{v}/" in ex or f"/{v}/" in "/" + ex for ex in row.get("examples", []))


def load_words() -> set[str]:
    for p in ("/usr/share/dict/words", "/usr/share/dict/american-english"):
        if os.path.exists(p):
            return {w.strip().lower() for w in open(p, encoding="utf-8", errors="ignore") if w.strip()}
    return set()


def alnum_len(s: str) -> int:
    return len(re.findall(r"[A-Za-z0-9]", s))


def is_common(s: str, words: set[str]) -> bool:
    t = s.lower().strip()
    return t in STOP or t in words or alnum_len(t) < 4 or re.fullmatch(r"[\d\W_]+", t) is not None


def expand(value: str, kind: str) -> list[tuple[str, str]]:
    """Derive extra surface forms (e.g. DOMAIN\\user -> user, email -> domain)."""
    out = [(value, kind)]
    v = value.strip()
    m = re.fullmatch(r"([A-Za-z0-9-]{2,15})\\+([A-Za-z0-9._-]{2,30})(?:\s*\((.*)\))?", v)
    if m:
        out += [(m.group(1), "account"), (m.group(2), "account")]
    if kind == "email" and "@" in v and valid_email(v):
        local, dom = v.rsplit("@", 1)
        out.append((local, "account"))
        if dom.lower() not in MAIL_PROVIDERS:
            out.append((dom, "domain"))
    if kind == "domain" and v.lower().startswith("www."):
        out.append((v[4:], "domain"))
    return out


def valid_email(v: str) -> bool:
    loc, dom = v.rsplit("@", 1)
    return (valid_host(dom) and dom == dom.lower() and len(dom.split(".")[-2]) >= 3
            and len(loc) >= 2 and re.search(r"[A-Za-z]", loc) is not None)


JUNK = re.compile(r"^[A-Za-z]?\d+[A-Za-z]?\d*$|^[a-f0-9]{4,}$|^(?:sketch|plane|boss|cut|extrude|fillet|"
                  r"part|body|component|assembly|config|default|drawing|sheet|view)\s*-?\d*$", re.I)
COMPONENT_VENDORS = re.compile(r"alibre|pcbnew|te connectivity|stmicro|mouser|snapeda|digi-?key|molex|"
                               r"monotype|sdrc|i-deas|würth|wurth|vishay|murata|samtec|harwin|jst|amphenol|"
                               r"texas instruments|analog devices|microchip|nxp|infineon|bourns|kemet|"
                               r"panasonic|omron|littelfuse|hirose|traceparts|cadenas|3dcontentcentral|"
                               r"grabcad|mcmaster|misumi|thingiverse|printables|ultralibrarian|componentsearch", re.I)


def is_junk(v: str, kind: str, files: int, from_path: bool) -> bool:
    if from_path:
        return False
    a = alnum_len(v)
    if JUNK.search(v) or COMPONENT_VENDORS.search(v):
        return True
    if a <= 4 and (files <= 1 or re.search(r"\d", v)):
        return True
    if kind == "account" and not re.search(r"[aeiouy]", v, re.I):
        return True
    # odd internal casing like 'BgfF' or 'aBCd' from binary noise
    core = re.sub(r"[^A-Za-z]", "", v)
    if 3 <= len(core) <= 6 and re.search(r"[a-z][A-Z]", core) and files <= 2:
        return True
    return False


def build(candidates_path: str, out_path: str) -> dict:
    data = json.loads(Path(candidates_path).read_text())
    words = load_words()
    reg: dict[str, dict] = {}
    for row in data["candidates"]:
        for value, kind in expand(row["value"], row["kind"]):
            v = re.sub(r"\s+", " ", clean(value))
            low = v.lower()
            if PLACEHOLDER.search(v) or VENDOR.search(v):
                continue
            if kind == "email" and ("@" not in v or not valid_email(v)):
                continue
            if is_junk(v, kind, row["files"], _from_path(row) and value == row["value"]):
                continue
            if kind == "domain" and not valid_host(v):
                continue
            if kind == "phone" and len(re.sub(r"\D", "", v)) < 8:
                continue
            if not v or alnum_len(v) < 2 or len(v) > 120:
                continue
            if low in STOP and not (row["kind"] in ("account", "project", "domain") and value == row["value"]
                                    and _from_path(row)):
                continue
            if "/" in v or "\\" in v or "://" in v or "=" in v:
                continue
            if kind == "domain" and low in MAIL_PROVIDERS:
                continue
            scope = "global"
            if kind in ("project",) and is_common(v, words):
                scope = "path"
            elif kind in ("account", "person", "company") and is_common(v, words):
                scope = "path"
            prev = reg.get(low)
            if prev is None or (prev["scope"] == "path" and scope == "global"):
                reg[low] = {"value": v, "kind": kind, "scope": scope,
                            "files": row["files"] if prev is None else max(prev["files"], row["files"])}
    out = {"identities": sorted(reg.values(), key=lambda r: -r["files"]),
           "defects": data.get("defects", {})}
    Path(out_path).write_text(json.dumps(out, indent=1))
    g = sum(1 for r in reg.values() if r["scope"] == "global")
    print(f"registry: {len(reg)} identities ({g} global, {len(reg) - g} path-only) -> {out_path}")
    return out
