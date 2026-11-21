"""Code / host / address harvester (owner: B).

  code     - part / document / vendor-part codes on pages or files with a BOM / part-number cue, and STEP PRODUCT ids/names
  host     - every hostname in text (URLs, www., e-mail domains) except schema namespaces and big generic platforms
  address  - "<suffix>, <postcode> <City>" and "<no> <WORDS> STREET|ROAD|... <CITY>" street lines
Usage: python -m deid.codes INPUT_DIR OUT.tsv [-j 28] [--max-repos 10]
OUT.tsv: kind<TAB>value ; OUT.tsv.stats: count<TAB>repos<TAB>kind<TAB>value   (private)
"""
import os
import re
import sys
from collections import Counter, defaultdict
from multiprocessing import Pool

CUE = re.compile(r"(?i)part\s*(?:no|number|#|nr)|p/n\b|\bqty\b|quantity|bill of materials|\bbom\b|article\s*(?:no|number)|art\.?\s*-?\s*nr|"
                 r"teilenummer|zeichnungsnummer|bestellnummer|sachnummer|order\s*(?:no|code|number)|\bmfr\b|manufacturer|vendor|supplier|"
                 r"dwg\.?\s*no|drawing\s*(?:no|number)|doc(?:ument)?\.?\s*(?:no|number)|item\s*no|catalog(?:ue)?\s*(?:no|number)|n[º°o]\s*de\s*pieza|"
                 r"referencia|r[ée]f[ée]rence|\bref\b|mpn|sku")
TOKEN = re.compile(r"(?<![A-Za-z0-9_\-\./])([A-Za-z0-9][A-Za-z0-9_\-\.\+]{2,48}[A-Za-z0-9\+])(?![A-Za-z0-9_\-])")
EXCL = [re.compile(x, re.I) for x in (
    r"^\d+(?:[.,]\d+)?(?:mm|cm|m|in|inch|ft|kg|g|lb|lbs|n|nm|kn|v|vac|vdc|a|ma|w|kw|mah|hz|khz|mhz|rpm|deg|s|ms|um|µm|mpa|gpa|psi|bar|l|ml|pcs|x)?$",
    r"^[MR]\d+(?:[.,]\d+)?(?:x\d+(?:[.,]\d+)?)*(?:mm)?$", r"^\d+(?:[.,]\d+)?x\d+(?:[.,]\d+)?(?:x\d+(?:[.,]\d+)?)*(?:mm)?$",
    r"^\d{1,2}-\d{2,3}(?:x\d.*)?$", r"^(?:ISO|DIN|EN|ANSI|ASME|ASTM|JIS|IEC|GB|BS|NF|UNI|SAE|NAS|MS|AN|IPC|UL|CSA|IEEE|AWS|AISI)[\-_ ]?\d",
    r"^\d{4}-T\d+$", r"^(?:AISI|SS|SUS|AL|A|S|C|X|EN-?AW-?)\d{2,4}[A-Z]?$", r"^\d{1,2}[./-]\d{1,2}[./-]\d{2,4}$", r"^\d{4}[./-]\d{1,2}[./-]\d{1,2}",
    r"^v?\d+(?:\.\d+){1,2}[a-z]?$", r"^rev\.?[a-z0-9]{0,3}$", r"^(?:19|20)\d{2}$", r"^\d+:\d+$", r"^[A-Z]\d{1,2}$", r"^IT\d+$", r"^Ra\d",
    r"^(?:UNC|UNF|NPT|BSP|G)\d", r"^\d+(?:/\d+)+", r"^0x[0-9a-f]+$", r"^[0-9a-f]{12,}$", r"^(?:page|sheet|fig|figure|table|step|item|chapter|section)\d",
    r"^\d+(?:st|nd|rd|th)$", r"^(?:pla|abs|petg|tpu|pom|ptfe|pvc|hdpe|nbr|epdm)\d*$", r"^(?:usb|rs|i2c|spi|uart|can|ip|ipv)\d", r"^(?:mp3|mp4|h264|utf8|utf-8|x86|x64|arm64|win32|win64|3d|2d)$",
    r"^\d+[a-z]?$",  # plain numbers handled separately (need a label right before)
)]
NUMLABEL = re.compile(r"(?i)(?:part\s*(?:no|number|#)|p/n|article\s*(?:no|number)|art\.?\s*-?\s*nr|ref|order\s*(?:no|code)|item|réf|"
                      r"supplier\s*(?:no|number)|r[ée]f|mpn|sku|dwg\.?\s*no|doc(?:ument)?\.?\s*no)\s*[:.#]?\s*(\d{6,14})\b")
STEPPROD = re.compile(r"PRODUCT\s*\(\s*'([^']{3,60})'\s*,\s*'([^']{0,60})'")
HOST = re.compile(r"(?<![A-Za-z0-9\-\.@])((?:[a-z0-9](?:[a-z0-9\-]{0,40}[a-z0-9])?\.)+(?:com|org|net|edu|gov|io|co|de|uk|nz|au|ch|fr|it|es|nl|"
                  r"be|at|se|no|dk|fi|pl|cz|hu|jp|cn|kr|in|br|mx|ca|us|eu|ws|info|biz|tech|dev|app|ai|me|tv|cc|xyz|ru|pt|gr|ro|il|tw|sg|hk|za|ar|cl)"
                  r"(?:\.[a-z]{2})?)(?![A-Za-z0-9\-])", re.I)
PUBLIC = re.compile(r"(?i)(?:^|\.)(?:w3\.org|openxmlformats\.org|purl\.org|adobe\.com|microsoft\.com|xml\.org|iana\.org|schema\.org|xmlsoap\.org|"
                    r"github\.com|githubusercontent\.com|gitlab\.com|google\.com|googleapis\.com|youtube\.com|youtu\.be|wikipedia\.org|"
                    r"creativecommons\.org|gnu\.org|opensource\.org|apache\.org|mozilla\.org|python\.org|example\.com|example\.org|"
                    r"localhost|doi\.org|archive\.org|w3schools\.com|stackoverflow\.com|apple\.com|ietf\.org|unicode\.org|oasis-open\.org)$")
FILEEXT = re.compile(r"(?i)\.(?:prt|asm|drw|par|psm|catpart|catproduct|pdf|step|stp|stl|iges|igs|dxf|dwg|sldprt|sldasm|slddrw|ipt|iam|idw|f3d|fcstd|obj|3mf|png|jpg|jpeg|gif|svg|"
                     r"txt|md|csv|xlsx|xls|docx|doc|zip|gz|html|htm|xml|json|py|c|h|cpp|js|ini|cfg|exe|dll|so|log|bin|hex|ino|scad|gcode|nc)$")
ADDR1 = re.compile(r"(?:GmbH|AG|KG|Ltd\.?|Inc\.?|S\.L\.|B\.V\.|Oy|A/S|s\.r\.o\.|e\.V\.|SE)\s*[,;]\s*((?:D-|DE-|A-|CH-)?\d{4,5}\s[A-ZÄÖÜ][a-zäöüß]+(?:-[A-ZÄÖÜ][a-zäöüß]+)?)")
ADDR2 = re.compile(r"\b(\d{1,5}[A-Za-z]?\s(?:[A-Z][A-Za-z]+\s){1,3}(?i:street|st\.|road|rd\.?|avenue|ave\.?|drive|dr\.|lane|ln\.|way|boulevard|blvd\.?|"
                   r"place|pl\.|court|ct\.|highway|hwy)(?:\s[A-Z][A-Za-z]+){0,2})\b")
ADDR3 = re.compile(r"\b([A-ZÄÖÜ][a-zäöüß]+(?:straße|strasse|str\.|weg|gasse|platz|allee|ring|damm)\s\d{1,4}[a-z]?)\b")
TEXT_EXT = {"txt", "md", "csv", "tsv", "xml", "html", "htm", "json", "step", "stp", "sch", "kicad_sch", "kicad_pcb", "ini", "cfg", "yaml", "yml",
            "rst", "scad", "bom"}


SKU = re.compile(r"^[A-Z0-9]{2,6}(?:-[A-Z0-9]{2,6}){2,5}$")
NUMCODE = re.compile(r"^\d{2,}(?:-\d{2,}){1,3}(?:-\d)?$|^\d+(?:\.\d+){3,}$")


def codeish(v):
    if FILEEXT.search(v) or len(v) < 4:
        return False
    if not re.search(r"\d", v):
        return bool(SKU.match(v)) and len(v) >= 8
    if not re.search(r"[A-Za-z]", v):
        return bool(NUMCODE.match(v)) and not re.match(r"^\d{1,4}-\d{1,2}-\d{1,4}$", v)
    return not any(x.search(v) for x in EXCL)


def scan_text(t, cue_ok=None):
    out = []
    cue = CUE.search(t) is not None if cue_ok is None else cue_ok
    if cue:
        for m in TOKEN.finditer(t):
            v = m.group(1).rstrip(".")
            if codeish(v):
                out.append(("code", v))
        for m in NUMLABEL.finditer(t):
            out.append(("code", m.group(1)))
    for m in HOST.finditer(t):
        h = m.group(1).lower().rstrip(".")
        if not PUBLIC.search(h) and not FILEEXT.search(h) and re.search(r"[a-z]{2}", h.split(".")[0]):
            out.append(("host", m.group(1)))
    for rx in (ADDR1, ADDR2, ADDR3):
        for m in rx.finditer(t):
            out.append(("address", m.group(1).strip()))
    return out


def _texts(path):
    ext = path.rsplit(".", 1)[-1].lower() if "." in os.path.basename(path) else ""
    try:
        if ext == "pdf":
            import fitz
            with fitz.open(path) as d:
                for i in range(min(len(d), 40)):
                    yield "page", d[i].get_text("text")
        elif ext in ("step", "stp"):
            with open(path, "rb") as fh:
                yield "step", fh.read(4_000_000).decode("utf-8", "ignore")
        elif ext in TEXT_EXT:
            with open(path, "rb") as fh:
                yield "text", fh.read(2_000_000).decode("utf-8", "ignore")
    except Exception:
        return


def repo_of(path, root):
    rel = os.path.relpath(path, root).split(os.sep)
    return "/".join(rel[:3]) if len(rel) >= 3 and rel[0] == "sources" else "/".join(rel[:2])


def scan_file(args):
    path, root = args
    c = Counter()
    for kind, t in _texts(path):
        if kind == "step":
            for m in STEPPROD.finditer(t):
                for g in m.groups():
                    g = g.strip()
                    if codeish(g):
                        c[("code", g)] += 1
            hdr = t[:6000]
            c.update(x for x in scan_text(hdr, cue_ok=False))
        else:
            c.update(scan_text(t))
    return repo_of(path, root), c


def main(argv):
    root, out = argv[0], argv[1]
    j = int(argv[argv.index("-j") + 1]) if "-j" in argv else 28
    mx = int(argv[argv.index("--max-repos") + 1]) if "--max-repos" in argv else 10
    paths = [os.path.join(d, f) for d, _, fs in os.walk(root) for f in fs]
    cnt = Counter()
    reps = defaultdict(set)
    with Pool(j) as pool:
        for rk, c in pool.imap_unordered(scan_file, ((p, root) for p in paths), chunksize=16):
            for k, n in c.items():
                cnt[k] += n
                reps[k].add(rk)
    kept = 0
    with open(out, "w") as fh, open(out + ".stats", "w") as fs:
        for (kind, v), n in cnt.most_common():
            r = len(reps[(kind, v)])
            fs.write(f"{n}\t{r}\t{kind}\t{v}\n")
            if kind == "code" and r > mx:
                continue
            fh.write(f"{'part' if kind == 'code' else 'domain' if kind == 'host' else 'address'}\t{v}\n")
            kept += 1
    print(f"files {len(paths)} candidates {len(cnt)} kept {kept}")




# ---- selection: stats -> clean list ------------------------------------------------------------------------------
EXCL2 = [re.compile(x, re.I) for x in (
    r"^\d+\s*awg$", r"^\d+\s*-?pins?$", r"^\d+p$", r"^UN[CFE]?-?\d", r"^\d+-UN[CFE]", r"^R\.\d", r"^[a-z]\d+\.\d+$", r"^AP2\d\d$", r"^AP24\d",
    r"^(?:LQFP|TQFP|QFN|DFN|SOIC|SOP|SOT|TSSOP|SSOP|MSOP|DIP|PDIP|BGA|LGA|SMD|TO|SC|SOD|DO|MELF|QFP|PLCC|WLCSP|HTSSOP|VQFN|UQFN)-?\d",
    r"_P\d", r"^\d{1,3}-\d{1,3}$", r"^\d{3,5}-[a-z]{1,2}$", r"^Y14\.", r"^\d+(?:[.,]\d+)?(?:mm|in)?[x×]\d", r"^(?:CC|BY|SA|NC)-",
    r"^(?:AISI|EN|AW|AL|SS|ST)\d", r"^\d+(?:[.,]\d+)?(?:mm|cm|kg|nm|uf|nf|pf|mh|uh|kohm|ohm|k|r|v|a|w|mw)$", r"^(?:rev|ver|v)[\-_.]?\d",
    r"^(?:sheet|page|fig|detail|section|view|item|step|part|no|nr)[\-_.]?\d", r"^\d+(?:st|nd|rd|th)$", r"^[a-z]{1,2}\d{1,2}$",
    r"^(?:m|g|r|w|t|h|n|c|p)\d+(?:[.,]\d+)?$", r"^\d+[a-z]$", r"^iso", r"^din", r"^gb\d", r"^jis",
    r"^(?:VDD|VCC|VSS|GND|VIN|VOUT|VBUS|VBAT|AVDD|DVDD|VREF|VIO|VDDIO|\+?\d+V\d*)(?:_|$)", r"^OHL", r"^CERN-OHL", r"-position$", r"^\d+X\.",
    r"^ASME", r"^ANSI", r"^CC-?BY", r"^GPL", r"^LGPL", r"^MIT-", r"^(?:P|PA|PB|PC|PD|PE|PF|GPIO|ADC|DAC|TIM|USART|UART|SPI|I2C)\d+(?:_|$)",
)]


def keep_value(kind, v, repos, max_repos):
    if kind == "address":
        return len(v) >= 6 and re.search(r"[A-Za-zÄÖÜäöüß]{3}", v) is not None and re.search(r"\d", v) is not None
    if kind == "host":
        return True
    if not v.isascii() or repos > max_repos or any(x.search(v) for x in EXCL2):
        return False
    return True


def select(stats, out, max_repos=3):
    n = 0
    with open(out, "w") as fh:
        for l in open(stats, encoding="utf-8", errors="ignore"):
            try:
                cnt, reps, kind, v = l.rstrip("\n").split("\t")
            except ValueError:
                continue
            if keep_value(kind, v, int(reps), max_repos):
                fh.write(f"{'part' if kind == 'code' else 'domain' if kind == 'host' else 'address'}\t{v}\n")
                n += 1
    return n


if __name__ == "__main__":
    if sys.argv[1:2] == ["select"]:
        print("selected", select(sys.argv[2], sys.argv[3], int(sys.argv[4]) if len(sys.argv) > 4 else 3))
    else:
        main(sys.argv[1:])
