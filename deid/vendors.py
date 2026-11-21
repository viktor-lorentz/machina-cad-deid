"""Vendor / manufacturer company-name harvester (owner: B).

Scans PDF page text and text-like files and emits candidate *global company* identities:
  - legal-suffix names        "<Cap words> Inc./Corp./GmbH/Ltd/LLC/AG/B.V./Oy/A/S/s.r.o./Kft/Co. KG ..."
  - labelled vendors          "Manufacturer:/Mfr:/MFG:/Vendor:/Supplier:/Brand:/Hersteller:/Lieferant:/Fabricante:/Proveedor: X"
  - trademark / copyright     "... trademark(s) of X", "(c)/© <year> [by] X"
  - STEP header organisation  FILE_NAME author/organization strings
  - known component vendors   a curated dictionary matched case-sensitively as whole words
Usage: python -m deid.vendors INPUT_DIR OUT.tsv [-j 16] [--min 1]
OUT.tsv: count<TAB>source<TAB>value   (private: contains corpus strings)
"""
import os
import re
import sys
from collections import Counter
from multiprocessing import Pool

SUFFIX = (r"(?:GmbH\s*&\s*Co\.?\s*KG|GmbH|AG|KG|Inc\.?|Incorporated|Corp\.?|Corporation|Ltd\.?|Limited|LLC|L\.L\.C\.|PLC|plc|"
          r"Co\.,?\s*Ltd\.?|Co\.?\s*Ltd\.?|S\.A\.|S\.L\.|S\.p\.A\.|s\.r\.l\.|S\.r\.l\.|s\.r\.o\.|B\.V\.|N\.V\.|Oy|AB|A/S|ApS|Kft\.?|"
          r"Pty\.?\s*Ltd\.?|SAS|SARL|Sp\.\s*z\s*o\.o\.|INC\.?|CORP\.?|CORPORATION|LTD\.?|LIMITED|GMBH|CO\.,?\s*LTD\.?)")
WORD = r"(?:[A-Z][A-Za-z0-9&'\-\.]*|[A-Z]{2,}|&|und|and|de|of|[a-z]{3,12}|spol\.)"
LEGAL = re.compile(r"(?<=[A-Za-z0-9\.]),?\s(" + SUFFIX + r")(?![A-Za-z])")
_CONN = {"&", "und", "and", "de", "of", "spol.", "+"}


def _legal_names(t):
    """Suffix match, then walk back over capitalised tokens; returns the exact surface span."""
    for m in LEGAL.finditer(t):
        w0 = max(0, m.start() - 120)
        toks = list(re.finditer(r"\S+", t[w0:m.start()]))
        start = None
        n = 0
        for i in range(len(toks) - 1, -1, -1):
            tok = toks[i].group()
            core = tok.rstrip(",")
            if tok.endswith((";", ":", ")", "]", "|")) or core.isdigit():
                if core.isdigit() and start is not None:  # "<postcode> <City> <Name> GmbH": drop the city
                    start = w0 + toks[i + 2].start() if n >= 2 else None
                break
            if core.endswith(".") and core not in ("DR.", "Dr.", "St.", "Mt.", "Bros.", "spol.") and len(core) > 2 and start is not None:
                break  # end of a previous sentence / previous company
            if core[:1].isupper() or core in _CONN:
                start = w0 + toks[i].start()
                n += 1
                if n >= 5:
                    break
            else:
                break
        if start is None:
            continue
        span = t[start:m.end()]
        span = re.sub(r"^(?:(?:&|und|and|de|of|\+|(?i:the|property|of|by|from|copyright|all|rights|reserved|made|for|to|at|with|see|contact|courtesy))\s+)+", "", span)
        if span and span[:1].isupper():
            yield span


LABEL = re.compile(r"\b(?i:manufacturer|mfr|mfg\.? by|vendor|supplier|brand|hersteller|lieferant|fabricante|proveedor|fournisseur|fabricant)"
                   r"\s*[:=]\s*([A-Z][A-Za-z0-9&\-]+(?:[ ][A-Z][A-Za-z0-9&\-]+){0,3})")
TM = re.compile(r"(?:trademarks?|trade dress|property) (?:owned by |of )(?:the )?([A-Z][A-Za-z0-9&\-\.]+(?:[ ,]{1,2}[A-Z][A-Za-z0-9&\-\.]+){0,4})")
COPY = re.compile(r"(?:©|\((?i:c)\)|(?i:copyright))\s*(?:(?i:copyright)\s*)?(?:[A-Za-z]{3,9}\.?,?\s*)?(?:\d{4}(?:\s*[-–]\s*\d{4})?,?\s*)(?:(?i:by)\s+)?"
                  r"([A-Z][A-Za-z0-9&\-\.]+(?:[ ,]{1,2}[A-Z][A-Za-z0-9&\-\.]+){0,4})")
STEPORG = re.compile(r"FILE_NAME\s*\((?:[^;]*?)\(\s*'([^']{3,80})'\s*\)\s*,\s*\(\s*'([^']{3,80})'\s*\)", re.S)
KNOWN = sorted({k.strip() for k in """McMaster-Carr|McMaster|Digi-Key|DigiKey|Mouser|Misumi|MISUMI|Adafruit|SparkFun|Pololu|igus|Igus|Bosch|Rexroth|Festo|
Thorlabs|Edmund Optics|Hiwin|HIWIN|Faulhaber|FAULHABER|Maxon|Robotis|ROBOTIS|Dynamixel|Arduino|ARDUINO|Raspberry Pi|Texas Instruments|
Analog Devices|STMicroelectronics|Würth|Wurth|Molex|TE Connectivity|Phoenix Contact|Wago|WAGO|Hirose|Samtec|Omron|OMRON|Keyence|KEYENCE|
Swagelok|Loctite|Bossard|Smooth-On|Nexperia|Vishay|Murata|Bourns|Littelfuse|KEMET|Panasonic|Microchip|Infineon|Espressif|Seeed|DFRobot|
Elegoo|ELEGOO|Mean Well|MEAN WELL|Meanwell|Lumberg|Harting|HARTING|Amphenol|Weidmüller|Schurter|Mitsubishi Electric|Yaskawa|Oriental Motor|
Nanotec|Trinamic|TRINAMIC|Item Industrietechnik|Robert Bosch|Bosch Rexroth|Norelem|norelem|Ganter|Fastenal|Grainger|RS Components|Farnell|
Newark|LCSC|Tektronix|Keysight|Rohde & Schwarz|Fluke|Vernier|OpenBuilds|ServoCity|Actobotics|goBILDA|GoBilda|REV Robotics|LulzBot|Lulzbot|
Prusa|Creality|Ultimaker|Bondtech|Thomson Linear|Misumi USA|Accu|Automation Direct|AutomationDirect|Pimoroni|Waveshare|Sunon|Noctua|
Delta Electronics|Nidec|Schaeffler|INA|Timken|Igus GmbH|Smooth On|Reprap Discount|Bambu Lab""".replace("\n", "").split("|")} - {""},
               key=len, reverse=True)
KNOWNRE = re.compile(r"(?<![A-Za-z0-9])(" + "|".join(re.escape(k) for k in KNOWN) + r")(?![A-Za-z0-9])")
# software / CAD vendors are reported separately (risky: watermarks, STEP originating_system)
SOFTWARE = re.compile(r"(?i)\b(?:solidworks|dassault|autodesk|siemens plm|ptc|st-developer|step tools|spatial corp|ansys|onshape|freecad|kicad|"
                      r"microsoft|adobe|apple|google|linux|mathworks|parametric technology)\b")
STOP = re.compile(r"(?i)^(?:the|this|all|any|our|your|a|an|see|refer|note|notes|part|parts|drawing|material|scale|sheet|date|title|rev|"
                  r"unless|dimensions|tolerances|third angle|do not|for|by|and|of|in|is|are|to|with|no|not|n/a|na|none|tbd|various|standard|"
                  r"local|any supplier|equivalent|or equiv|generic)\b")
TEXT_EXT = {"txt", "md", "csv", "tsv", "xml", "html", "htm", "json", "step", "stp", "bom", "sch", "kicad_sch", "kicad_pcb", "ini", "cfg", "yaml", "yml"}


def _texts(path):
    ext = path.rsplit(".", 1)[-1].lower() if "." in os.path.basename(path) else ""
    try:
        if ext == "pdf":
            import fitz
            with fitz.open(path) as d:
                for i in range(min(len(d), 8)):
                    yield d[i].get_text("text")
        elif ext in TEXT_EXT:
            with open(path, "rb") as fh:
                yield fh.read(3_000_000).decode("utf-8", "ignore")
    except Exception:
        return


def _clean(v):
    v = re.sub(r"\s+", " ", v).strip(" ,.;:-")
    if len(v) < 2 or len(v) > 70 or STOP.match(v) or not re.search(r"[A-Za-z]{2}", v):
        return None
    return v


def scan_text(t):
    out = []
    t1 = re.sub(r"[ \t]+", " ", t)
    for v in _legal_names(t1):
        v = _clean(v)
        if v:
            out.append(("software" if SOFTWARE.search(v) else "legal", v))
    for src, rx in (("label", LABEL), ("tm", TM), ("copy", COPY)):
        for m in rx.finditer(t1):
            v = _clean(m.group(1))
            if v:
                out.append((src if not SOFTWARE.search(v) else "software", v))
    for m in STEPORG.finditer(t[:20000]):
        for g in m.groups():
            v = _clean(g)
            if v and not re.search(r"(?i)unknown|none|^\W*$", v):
                out.append(("software" if SOFTWARE.search(v) else "steporg", v))
    for m in KNOWNRE.finditer(t1):
        out.append(("known", m.group(1)))
    return out


def scan_file(path):
    c = Counter()
    for t in _texts(path):
        c.update(scan_text(t))
    return c


def main(argv):
    root, out = argv[0], argv[1]
    j = int(argv[argv.index("-j") + 1]) if "-j" in argv else 16
    mn = int(argv[argv.index("--min") + 1]) if "--min" in argv else 1
    paths = [os.path.join(d, f) for d, _, fs in os.walk(root) for f in fs]
    tot = Counter()
    with Pool(j) as p:
        for c in p.imap_unordered(scan_file, paths, chunksize=16):
            tot.update(c)
    with open(out, "w") as fh:
        for (src, v), n in tot.most_common():
            if n >= mn:
                fh.write(f"{n}\t{src}\t{v}\n")
    by = Counter()
    for (src, _), n in tot.items():
        by[src] += 1
    print(f"files {len(paths)} candidates {len(tot)} by source {dict(by)}")


if __name__ == "__main__":
    main(sys.argv[1:])
