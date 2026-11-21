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
VENDOR = re.compile(r"^github\.com$|^gitlab\.com$|creativecommons\.org|free software foundation|^gnu\.org$|opensource\.org|^www\.github\.com$|kicad|stepup|ksu mcad|zwcad|step tools|steptools|3ds\.com|netfabb|matplotlib|cairograph|"
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


NAME_STOP = set("""
figure figures fig table copier user users max min using non python ontario radsatz ownerid owner admin
january february march april may june july august september october november december manual guide
installation instructions plano nitronic refrigera od id\n
advance bill materials material custom standard here quantity qty item part parts number no nº drawing
drawings dwg sheet scale size rev revision date title approved checked drawn design designed tolerance
tolerances iso din ansi gb jis unless otherwise specified dimensions finish weight mass description
desenho pelo qual foi subsituido anders definiert information only welded aluminum steel stainless
general notes note section detail view assembly unit units mm inch inches projection first third angle
""".split())


PHRASE_WORDS = set("""the of in and or for any be by to a an is are this that be their its it shall not from with
without all rights reserved liable claim holders owners respective united states property copyright software
provided as warranty damages notice permission""".split())


def _bad_name(v: str, kind: str) -> bool:
    toks = re.findall(r"[^\W\d_]+", v.lower())
    if " " in v and v == v.lower() and sum(t in PHRASE_WORDS for t in toks) >= 1:
        return True  # lowercase prose fragment, not a name
    if re.search(r"\d", v) or re.fullmatch(r"[a-z]{2}-[A-Z]{2}", v):
        return True
    if not toks or all(t in NAME_STOP for t in toks):
        return True
    if kind == "person":
        if sum(t in NAME_STOP for t in toks) >= max(1, len(toks) // 2):
            return True
        if len(toks) == 1 and (v.isupper() or len(v) <= 4):
            return True
    if kind == "company":
        if toks[-1] in NAME_STOP or len(re.sub(r"\W", "", v)) <= 3:
            return True
        if re.search(r"(?i)\bfor information only\b", v):
            return True
    return False


STANDARD_CODE = re.compile(
    r"(?i)^(?:iso|din|en|gb|gbt|ansi|asme|jis|uni|iec|nema|aisi|sae|astm|bs|nf|csa|ul|ieee|ipc|mil|"
    r"rev|ver|version|v\d|r\d|m\d|sheet|page|fig|draft|copy|scan|img|image|dsc|screenshot|photo|"
    r"untitled|drawing|part|assembly|assy|asm|model|test|sample|new|old|backup|final)(?=[-_.\d]|$)"
    r"|^\d+x\d+|^[mM]\d+x\d+|x\d+mm$|^\d{4}-\d{2}-\d{2}")


MAIL_PROVIDERS_SLD = {"tinyurl", "pdftk", "matweb", "netsplit", "cadclick", "bitly", "dropbox", "thingiverse",
                      "grabcad", "instructables", "printables", "onshape", "autodesk", "solidworks", "mcmaster",
                      "digikey", "mouser", "farnell", "adafruit", "sparkfun", "arduino", "raspberrypi",
                      "sourceforge", "readthedocs", "creativecommons", "openhardware", "hackaday","gmail", "yahoo", "hotmail", "outlook", "live", "icloud", "proton", "protonmail", "aol",
                      "github", "gitlab", "google", "amazon", "microsoft", "apple", "wikipedia", "youtube",
                      "facebook", "twitter", "linkedin", "instagram", "googlemail", "mail", "email", "inbox"}


SIGNAL_SEGS = set("""io gpio pwr en vcc vdd gnd vss miso mosi sck sclk scl sda cs ss tx rx txd rxd clk rst nrst
reset osc bga nc dqs dq adc dac pwm int irq usb spi i2c uart jtag tck tms tdi tdo swd swclk swdio led btn
sw ph pa pb pc pd pe pf pg vin vout vbat vbus mclk lrclk bclk sdin sdout cmd dat d0 d1 d2 d3 a0 a1 a2 a3
t0 t1 t2 t3 l1p l1n l2p l2n""".split())


def _is_signal_name(v: str) -> bool:
    """Schematic net / FPGA pin names (IO_L9P_T1_DQS_AD3P_15, USB2_PWR_EN) and distributor SKUs."""
    segs = [x.lower() for x in re.split(r"[-_.]", v) if x]
    if v.upper().endswith("-ND"):
        return True
    return sum(x in SIGNAL_SEGS or re.fullmatch(r"(io|l\d+[pn]|t\d|ad\d+[pn]?|p\d+)", x) is not None
               for x in segs) >= 2


FILE_EXT_RX = re.compile(r"\.(?:sldprt|sldasm|slddrw|step|stp|stl|iges|igs|ipt|iam|idw|dwg|dxf|pdf|par|psm|asm|"
                         r"prt|drw|catpart|catproduct|x_t|x_b|sat|f3d|fcstd|3mf|obj|wrl|png|jpg|svg|zip|txt)$",
                         re.I)


_ORG_HEAD = re.compile(r"(?i)\b(institute|institut|university|universit[äéy]|laboratory|college|fundaci[óo]n?|"
                       r"hochschule|politecnico|polytechnic)\b")


def _interleaved_org(v: str) -> bool:
    """Two-column title blocks interleave lines: 'Institute of Technology Massachusetts Institute'."""
    toks = v.split()
    return len(_ORG_HEAD.findall(v)) > 1 or (toks and toks[0].lower() in
                                               {"technology", "engineering", "science", "sciences", "of", "and"})


def is_junk(v: str, kind: str, files: int, from_path: bool) -> bool:
    if from_path or kind == "part":  # part numbers were filtered by their own rules
        return False
    a = alnum_len(v)
    if JUNK.search(v) or COMPONENT_VENDORS.search(v):
        return True
    if a <= 4 and (files <= 1 or re.search(r"\d", v)):
        return True
    if kind == "account" and not re.search(r"[aeiouy]", v, re.I):
        return True
    if kind in ("person", "company", "account", "project") and " " in v and _bad_name(v, kind):
        return True
    if kind == "part":
        return False
    if kind in ("person", "company") and _bad_name(v, kind):
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
    field_rows = [r for r in data["candidates"] if r["kind"].endswith("_field")]
    pdf_codes = {r["value"] for r in data["candidates"] if r["kind"] in ("dwgno", "codechain")}
    for row in data["candidates"]:
        if row["kind"] == "person_near":
            # surname found near a title-block label: keep only project-local words
            # (language words recur across many unrelated repositories)
            from deid.formats.pdftext import near_word_ok

            last = row["value"].split(".")[-1].strip()
            if row.get("repos", 0) > 5 or row.get("files", 0) < 2 or not re.search(r"[a-z]", row["value"], re.I) \
                    or not near_word_ok(last):
                continue
            row = dict(row, kind="person")
        if row["kind"] in ("project_label", "project_camel"):
            if row["kind"] == "project_camel" and (row.get("repos", 0) > 3 or row.get("files", 0) < 2):
                continue
            if row.get("repos", 0) > 5:
                continue
            row = dict(row, kind="project")
        if row["kind"] == "company" and _interleaved_org(row["value"]):
            continue
        if row["kind"] == "person_init":
            sur = re.split(r"\.\s?", row["value"])[-1].lower()
            from deid.formats.pdftext import TECH_STOP, _common_words

            if row.get("repos", 0) > 5 or sur in TECH_STOP or sur in _common_words():
                continue
            row = dict(row, kind="person")
        if row["kind"] == "codechain":
            # upper-case code chains printed in PDFs: keep project-local ones that recur
            if row.get("repos", 0) > 2 or STANDARD_CODE.search(row["value"]):
                continue
            row = dict(row, kind="dwgno")
            mode_ok = os.environ.get("DEID_PARTS", "smart") != "none"
            if not mode_ok:
                continue
        if row["kind"] in ("partno", "dwgno", "codechain"):
            v0 = FILE_EXT_RX.sub("", row["value"])
            if v0 != row["value"]:
                if len(v0) < 4:
                    continue
                row = dict(row, value=v0)
        if row["kind"] in ("partno", "dwgno"):
            # DEID_PARTS: none | smart (default: PDF-printed codes only) | all (also bare file-name codes)
            mode = os.environ.get("DEID_PARTS", "smart")
            from_pdf_text = row["kind"] == "dwgno" or "pdf" in row.get("formats", {})
            if mode == "none" or (mode == "smart" and not from_pdf_text):
                continue
            if row["kind"] == "partno" and mode == "smart" and row["value"] not in pdf_codes:
                continue
            if row.get("repos", 0) > 5 or STANDARD_CODE.search(row["value"]) or _is_signal_name(row["value"]):
                continue
            pv = row["value"]
            # vendor catalogue numbers (pure digits) and short model codes / fragments are not project identities
            if len(pv) < 6 or not re.search(r"[A-Za-z]", pv) or not re.search(r"\d", pv) or not pv.isascii():
                continue
            row = dict(row, kind="part")
            # identifying part / document numbers: project-local codes only
            v0 = row["value"]
            if row.get("repos", 0) > 5 or STANDARD_CODE.search(v0) or re.fullmatch(r"(?i)v?\d+([._]\d+)+[a-z]?", v0):
                continue
            row = dict(row, kind="part")
        field_kind = None
        if row["kind"].endswith("_field"):
            # explicit identity field (OLE author / last saved by): always pseudonymised in
            # that field, even when the value is a generic or common word
            field_kind = row["kind"][:-6]
            row = dict(row, kind=field_kind)
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
    # institution acronyms from their domains: ethz.ch -> ETHZ, nait.ca -> NAIT
    for r in list(reg.values()):
        if r["kind"] in ("domain", "email") and r["scope"] == "global":
            host = r["value"].split("@")[-1].lower()
            labels = host.split(".")
            if len(labels) >= 2:
                sld = labels[-2] if labels[-2] not in ("ac", "co", "com", "edu", "org", "gov") or len(labels) < 3 else labels[-3]
                if 4 <= len(sld) <= 8 and sld.isalpha() and sld not in words and sld not in MAIL_PROVIDERS_SLD \
                        and not VENDOR.search(sld) and sld not in reg:
                    reg[sld] = {"value": sld.upper(), "kind": "company", "scope": "global", "files": r["files"]}
    for row in field_rows:
        v = re.sub(r"\s+", " ", clean(row["value"]))
        if v and v.lower() not in reg and alnum_len(v) >= 2 and len(v) <= 80 and not PLACEHOLDER.search(v):
            reg[v.lower()] = {"value": v, "kind": row["kind"][:-6], "scope": "field", "files": row["files"]}
    out = {"identities": sorted(reg.values(), key=lambda r: -r["files"]),
           "defects": data.get("defects", {})}
    Path(out_path).write_text(json.dumps(out, indent=1))
    g = sum(1 for r in reg.values() if r["scope"] == "global")
    print(f"registry: {len(reg)} identities ({g} global, {len(reg) - g} path-only) -> {out_path}")
    return out
