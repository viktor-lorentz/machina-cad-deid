"""PDF page text: harvest title-block identities and replace them in place.

Harvest (rule based, multilingual title-block labels):
* e-mail addresses, web domains, phone numbers;
* names following drawing title-block labels (DRAWN, CHECKED, APPROVED,
  DESIGNED, AUTHOR, NAME, Gezeichnet, Geprueft, Dessine, 设计, 审核, ...);
* person names: 2-3 capitalised tokens starting with a known first name;
* organisations: capitalised words ending in a legal/institution suffix, and
  the owner in "PROPERTY OF ..." / "Copyright ... " notices.

Replace: PyMuPDF redaction that removes only the matched glyphs (vector line
art and images are kept) and writes the pseudonym into the same box, so page
geometry is unchanged and extracted text shows the pseudonym.
"""

from __future__ import annotations

import re

FIRST_NAMES = set("""
aaron abdul abhi adam adrian ahmed aitor alan albert alberto alejandro alex alexander alexandre alexandra
alexis alfonso alfred ali alice alicia amanda amir amit ana anand anders andre andrea andreas andrei andres
andrew andrés andy angel angela anna anne anthony antoine anton antonio arjun arnaud arthur ashley aurelien
axel ben benedikt benjamin bernard bernd bill bob boris brad brandon brian bruno carl carla carlo carlos
carmen carol caroline catherine cedric cesar charles charlie chen chris christian christina christine
christoph christophe christopher claire claude claudia colin connor craig cristian daniel daniela danny
dario dave david dean denis dennis diana diego dimitri dmitry dominik dominique don doug douglas edgar
eduardo edward elena elias elisa emil emily emma enrico eric erik ernesto esteban ethan eugene eva evan
fabian fabio fabrice federico felipe felix fernando filip florian francesco francis francisco franck
francois françois frank franz fred frederic frédéric gabriel gareth gary george georg gerard gerhard
giorgio giovanni giuseppe gonzalo gordon graham greg gregor gregory guido guillaume guillermo gustavo hans
harald harry hector heinz helen helmut henri henrik henry hiroshi hugo ian igor ignacio ilya isaac ivan
jack jacob jacques jaime jake james jan jane janet jason javier jean jeff jeffrey jennifer jens jeremy
jerome jérôme jesse jesus jesús jim jimmy joachim joan joao joe joel johan johann johannes john jon jonas
jonathan jordi jorge jose josé joseph josh joshua juan julia julian julien julio justin kai karl karsten
kate katharina keith ken kenji kevin klaus kurt lars laura laurent lee leo leon leonardo lisa lorenzo
louis luc luca lucas luis lukas luke magnus manuel marc marcel marco marcos marcus maria mario mark markus
martin mary massimo mathieu matt matteo matthew matthias max maxim maxime michael michel michele miguel
mike mikhail milan mohamed mohammad nathan neil nicholas nick nico nicola nicolas nicolás niels nikolai
nils noah olaf oliver olivier omar oscar pablo paolo pascal patrick paul pedro peter petr phil philip
philipp philippe pierre pietro piotr rafael rainer ralf ralph ramon raphael raul raúl ravi ray raymond
remi rené rene ricardo richard rick robert roberto robin rodrigo roger roland roman ronald rudolf ryan
salvador sam samuel sandra sara sarah sascha scott sean sebastian sebastien sébastien sergei sergey sergio
simon simone stefan stefano stephan stephane stéphane stephen steve steven sven takashi thomas thierry tim
timo timothy tobias todd tom tomas tomás tony torsten uwe valentin vasily victor vincent vladimir walter
wei werner william wolfgang xavier yann yuki yuri yves zhang
bernat jordi pere pau oriol marc arnau senthur raj rahul priya arun vijay suresh ramesh ankit amit deepak
maurice clemens nikita dmitri sergej anatoly yusuf mehmet emre burak murat ahmet fatih kemal hakan
lars bjorn björn sven nils kristian henrik mikael jukka matti pekka antti teemu ville tuomas
piet jan joost bram sander ruud wouter maarten jeroen thijs koen niels bas rik
lukasz łukasz tomasz krzysztof marcin pawel paweł michal michał jakub wojciech marek
hiroshi takeshi kenji satoshi daisuke yuki haruto sota ren kaito hina yui
wei jun jie hao yang ming lei feng chao bo xin hui ying ling
giulia chiara francesca alessandro davide simone federica luigi fabrizio
gustav ingrid astrid sigrid freya

""".split())

LABELS = (r"drawn(?:\s+by)?|dwn|drn|checked(?:\s+by)?|chk|chkd|approved(?:\s+by)?|appr?|designed(?:\s+by)?|"
          r"designer|engineer|author|created\s+by|creator|made\s+by|prepared\s+by|reviewed\s+by|"
          r"gezeichnet|gezeich\.|gepr(?:ü|ue)ft|bearbeitet|bearb\.|konstrukteur|ersteller|"
          r"dessin(?:é|e)|v(?:é|e)rifi(?:é|e)|auteur|approuv(?:é|e)|dibujado|revisado|disegnato|controllato|"
          r"设计|審核|审核|校核|校对|批准|制图|绘图|作成者|設計|担当")
LABEL_RX = re.compile(rf"(?:^|\s)(?i:{LABELS})\s*[:：.]?[ \t]+([A-Z][A-Za-z.'-]{{1,20}}(?:[ \t]+[A-Z][A-Za-z.'-]{{1,20}}){{0,2}})")
ORG_SUFFIX = (r"GmbH|AG|Inc\.?|Ltd\.?|LLC|L\.L\.C\.|Corp\.?|Corporation|Company|Co\.,?\s?Ltd\.?|S\.A\.S?\.?|SAS|"
              r"S\.r\.l\.|SRL|B\.V\.|BV|Oy|AB|A/S|Pty\.?\s?Ltd\.?|Institute|Institut|University|Universit(?:ä|a)t|"
              r"Universit(?:é|e)|Universidad|Universit(?:à|a)|Laboratory|Laboratories|Labs?|College|Foundation")
ORG_RX = re.compile(rf"\b((?:[A-Z][A-Za-z&'.-]{{1,25}}\s+){{1,5}}(?:{ORG_SUFFIX}))(?![A-Za-z])")
ORG_PREFIX_RX = re.compile(r"\b((?:University|Universit(?:ä|a)t|Universit(?:é|e)|Universidad|Institute|Institut|"
                           r"Technische Universit(?:ä|a)t)\s+(?:of\s+|de\s+|du\s+|für\s+)?(?:[A-Z][A-Za-z-]{2,25}\s*){1,3})")
PROPERTY_RX = re.compile(r"(?:PROPERTY\s+OF|EIGENTUM\s+(?:DER|VON)|PROPRI(?:É|E)T(?:É|E)\s+DE|COPYRIGHT\s*(?:\(C\)|©)?\s*(?:\d{4}\s*)?)"
                         r"\s+((?:[A-Z][A-Za-z&.,'-]+\s*){1,6})", re.I)
EMAIL_RX = re.compile(r"[A-Za-z0-9._%+-]{2,64}@[a-z0-9-]{2,63}(?:\.[a-z0-9-]{2,63})*\.[a-z]{2,12}")
URL_RX = re.compile(r"(?:https?://|www\.)([a-z0-9-]{2,63}(?:\.[a-z0-9-]{2,63})+)", re.I)
PHONE_RX = re.compile(r"(?<![\d.,/])(?:\+\d{1,3}[\s.-]?)?(?:\(\d{2,5}\)[\s.-]?)?\d{2,4}(?:[\s.-]\d{2,4}){2,4}(?![\d.,/])")
NAME_TOKEN = r"[A-ZÀ-Ý][a-zà-ÿ'-]{1,20}|[A-ZÀ-Ý]{2,20}"
PERSON_RX = re.compile(rf"\b((?:{NAME_TOKEN})(?:[ \t]+(?:(?:de|da|del|van|von|der|di|le|la)[ \t]+)?(?:{NAME_TOKEN})){{1,5}})\b")
STOPWORDS = {"drawn", "checked", "approved", "date", "scale", "sheet", "title", "material", "finish", "size",
             "rev", "revision", "weight", "part", "number", "name", "dwg", "projection", "tolerances", "unless",
             "otherwise", "specified", "dimensions", "section", "detail", "view", "assembly", "drawing", "do",
             "not", "the", "and", "of", "for", "all", "see", "note", "notes", "qty", "item", "description",
             "mass", "quantity", "units", "page", "file", "angular", "general", "surface", "general", "standard", "type",
             "model", "design", "designed", "engineer", "approval", "manufacturer", "supplier", "project"}


def _clean_name(s: str) -> str:
    toks = s.strip(" .,;:-").split()
    while toks and toks[-1].lower().strip(".:") in STOPWORDS:
        toks.pop()
    while toks and toks[0].lower().strip(".:") in STOPWORDS:
        toks.pop(0)
    return " ".join(toks)


NEAR_LABEL_RX = re.compile(
    r"(?i)\b(?:drawn|checked|approved|designed|designer|reviewer|reviewed|issued|author|engineer|drafter|"
    r"dessin(?:é|e)|v(?:é|e)rifi(?:é|e)|gezeichnet|gepr(?:ü|ue)ft|bearbeitet|disegnato|controllato|approvato|"
    r"verificato|dibujado|revisado|aprobado|desenhado|verificado)\b")
NAME_NEAR_RX = re.compile(r"(?<![\w.])([A-ZÀ-Ý][a-zà-ÿ]{3,20}|[A-ZÀ-Ý]{4,20})(?![\w])")
INITIAL_NAME_RX = re.compile(r"(?<![\w.])([A-Z]\.\s?[A-ZÀ-Ý][a-zà-ÿ]{2,20})(?![\w])")
TECH_STOP = set("""
drawn checked approved designed designer reviewer reviewed issued author engineer drafter date scale sheet
title material finish size revision weight mass description quantity tolerance tolerances projection
dimensions general notes note section detail view assembly drawing part number code standard unless
otherwise specified angle third first surface roughness treatment thread holes hole thru deep chamfer
fillet radius typ ref zone change changes modified added removed release released rev issue status
aluminium aluminum steel stainless brass copper plastic nylon delrin anodised anodized black white
dessine verifie gezeichnet gepruft geprueft bearbeitet datum name masstab maßstab werkstoff blatt
benennung zeichnung hinweis abmessungen toleranzen oberfläche disegnato controllato approvato verificato
data scala foglio materiale descrizione quota tolleranze revisione dibujado revisado aprobado fecha
escala hoja materiel matériau échelle feuille désignation nom projet drawings model models iso din ansi
""".split())
TECH_STOP |= set("""
chamfer chamfers undim undimensioned geometr geometry workspace spacer spacers cuvette acetal copolymer
impeller assemb assembl aproved approvd galvo recoater dehuller unmodelled proto quant permis stirling plade
zchng arduino january february march april may june july august september october november december
jan feb mar apr jun jul aug sep sept oct nov dec monday tuesday wednesday thursday friday russia canada
london china germany france italy spain japan usa india europe kazan glencoe workshop prototype bearing
bracket housing cover plate shaft gear motor mount holder washer bushing nozzle sensor frame
numbe breadboard gesamtzeichng boden elemente element preamp stepper arbeit auftrag micro asembly benchtop
kontextmenu bohrung gewinden gewinde skizze volumen skizzenmodus carraige carriage codice rugosità massa ptype
sistem weldment gearmotor gripper changer goniometer piezo stanzwerkzeug lehrprodukt magnetiic sistema
galvomount bundplade dynamixel nikon mitutoyo thorlabs american scottish kelvin ergocub
projekt anhang zeichen skizzen bohrungen walze öffnen animationen kontrolliert geprüft gezeichnet
änderungen änderung stückliste gesamtmasse volumenmodelle baugruppen explosionszeichnungen allgemeintoleranz
""".split())
GERMAN_SUFFIX = re.compile(r"(?:ung|ungen|platte|deckel|liste|masse|modell|modelle|zeichnung|zeichnungen|gruppe|"
                           r"gruppen|teil|teile|kranz|fläche|bild|weise|toleranz|block|blech|rad|keit|heit|lich|"
                           r"iert|ieren|schaft|stück|stange|welle|lager|halter|scheibe|schraube|mutter|feder|"
                           r"gehäuse|rahmen|profil|winkel|platten|nen|chen)$")
_COMMON: set | None = None


def _common_words() -> set:
    global _COMMON
    if _COMMON is None:
        _COMMON = set()
        for p in ("/usr/share/dict/words", "/usr/share/dict/american-english"):
            try:
                with open(p, encoding="utf-8", errors="ignore") as f:
                    _COMMON = {w.strip() for w in f if w.strip() and w.strip().islower()}
                break
            except OSError:
                continue
    return _COMMON


def near_word_ok(w: str) -> bool:
    lw = w.lower()
    if lw in TECH_STOP or lw in STOPWORDS or (GERMAN_SUFFIX.search(lw) and len(lw) > 7):
        return False
    stems = {lw, lw.rstrip("s"), re.sub(r"(ed|ing|ly|es|er)$", "", lw), re.sub(r"(d|ing)$", "", lw)}
    return not any(x in _common_words() for x in stems)


def _near_label_names(text: str) -> list[tuple[str, str]]:
    common = _common_words()
    out = []
    for lm in NEAR_LABEL_RX.finditer(text):
        a, b = max(0, lm.start() - 90), min(len(text), lm.end() + 90)
        win = text[a:b]
        for m in NAME_NEAR_RX.finditer(win):
            w = m.group(1)
            lw = w.lower()
            # skip words cut by the window edges
            if (m.start() == 0 and a > 0 and text[a - 1].isalpha()) or \
                    (m.end() == len(win) and b < len(text) and text[b].isalpha()):
                continue
            if GERMAN_SUFFIX.search(lw) and len(lw) > 7:
                continue
            stems = {lw, lw.rstrip("s"), re.sub(r"(ed|ing|ly|es|er)$", "", lw), re.sub(r"(d|ing)$", "", lw)}
            if lw in TECH_STOP or lw in STOPWORDS or any(x in common for x in stems):
                continue
            out.append((w, "person_near"))
        for m in INITIAL_NAME_RX.finditer(win):
            sur = m.group(1).split(".")[-1].strip().lower()
            if sur not in common and sur not in TECH_STOP:
                out.append((m.group(1), "person_near"))
    return out


def _split_people(tokens: list[str]) -> list[str]:
    """Split 'Marcos Briones Jon Castillo' into ['Marcos Briones', 'Jon Castillo']."""
    people, cur = [], []
    for t in tokens:
        if cur and len(cur) >= 2 and t.lower() in FIRST_NAMES:
            people.append(" ".join(cur))
            cur = []
        cur.append(t)
    if cur:
        people.append(" ".join(cur))
    return people


DWGNO_RX = re.compile(r"(?i)(?:drawing\s*(?:code|no\.?|number)|dwg\.?\s*no\.?|part\s*(?:no\.?|number)|"
                      r"document\s*(?:no\.?|number)|doc\.?\s*no\.?|item\s*no\.?|zeichnungs?-?nr\.?|"
                      r"zeichnungsnummer|sachnummer|teilenummer|n[°º]\s*plan|codice|图号|图样代号|零件代号)"
                      r"\s*[:：.]?\s*([A-Za-z0-9][A-Za-z0-9_.-]{4,40})")


LIGO_RX = re.compile(r"(?<![A-Za-z0-9])([A-Z]\d{6,7}(?:-(?:v?\d{1,3}|[A-Z]{1,2})){0,2})(?![A-Za-z0-9])")
CODECHAIN_RX = re.compile(r"(?<![A-Za-z0-9_.-])([A-Z][A-Z0-9]{1,9}(?:[-_.][A-Z0-9]{1,10}){2,6})(?![A-Za-z0-9_-])")
INIT_SURNAME_RX = re.compile(r"(?<![\w.])([A-Z]\.\s?(?:[A-Z]\.\s?)?[A-ZÀ-Ý][A-Za-zà-ÿ]{2,20})(?![\w])")
_INST = (r"(?:INSTITUTE|Institute|UNIVERSITY|University|Institut|Instituto|Istituto|Fundació|Fundación|Fondazione|"
         r"Stiftung|LABORATORY|Laboratory|Laboratorio|Hochschule|Universität|Université|Universidad|Università|"
         r"Politecnico|Polytechnic)")
_CAPW = r"[A-ZÀ-Ý][A-Za-zÀ-ÿ'-]+"
INSTITUTION_RX = re.compile(
    rf"((?:{_CAPW}[ \t]+){{0,2}}{_INST}(?:[ \t]+(?:of|OF|für|FÜR|de|DE|for|FOR|di|DI|del|des|du)"
    rf"(?:[ \t]+(?:und|and|y|et|e|AND|UND)?[ \t]*{_CAPW}){{1,4}}|[ \t]+[A-Z]{{2,6}}\b))")
US_PHONE_RX = re.compile(r"(?<![\d.(])(\(\d{3}\)\s?\d{3}-\d{4}|\d{3}\.\d{3}\.\d{4})(?![\d.])")
DOTTED_PHONE_RX = re.compile(r"(?<![\d.])(\d{2,3}(?:\.\d{2,3}){3,4})(?![\d.])")


PROJECT_LABEL_RX = re.compile(r"(?i)\b(?:project(?:\s*name)?|projekt|projet|proyecto|progetto)\s*[:：]\s*"
                              r"([A-Z0-9][A-Za-z0-9+&.' -]{2,40}?)(?=\s{2,}|\n|$|\s+(?:date|drawn|scale|sheet|rev))")
CAMEL_RX = re.compile(r"(?<![A-Za-z0-9])([A-Za-z]*[a-z][A-Z][A-Za-z0-9+]*)(?![A-Za-z0-9])")
SOFTWARE_CAMEL = set("""solidworks freecad kicad autocad openscad onshape github gitlab youtube labview powerpoint
iphone ipad macos javascript typescript linkedin facebook wordpress sketchup inventor pcbnew eeschema
coreldraw photoshop illustrator acrobat adobe microsoft openoffice libreoffice microstation creo
catia nx siemens fusion autodesk solidedge spaceclaim designspark easyeda altium eagle orcad
mathworks matlab simulink ansys comsol abaqus paraview blender meshlab cura prusaslicer simplify3d
tplh tphl tpd hene subghz noir compactpci cia402 ice40up5k ultipanel mosfet igbt ethercat canopen modbus
profinet devicenet bluetooth zigbee lorawan wifi pcie mipi hdmi displayport thunderbolt
""".split())


_ALLOY = re.compile(r"^(?:(?:Al|Cu|Mg|Zn|Ni|Ti|Fe|Cr|Mo|Si|Pb|Sn|Mn|Co|Ag|Au|Pt|Nb|Zr|W|V|C|N|B)\d*(?:[.,]\d+)?)+$")
_CAMEL_OK = set("""pcb led usb sd cad cnc pla abs petg tpu io api id ui gui pdf xyz rgb dc ac ip mcu cpu gpu
dof dofs proj param params config init cfg tmp temp ref refs num img std
""".split())


def _plain_camel(w: str) -> bool:
    """CamelCase built only from ordinary words / units / element symbols (BasePlate, microSD, AlZnMgCu1)."""
    if _ALLOY.match(w):
        return True
    parts = [p.lower() for p in re.findall(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|\d+", w)]
    parts = [p for p in parts if not p.isdigit()]
    if not parts:
        return True
    words = _common_words()
    return all(p in words or p in TECH_STOP or p in _CAMEL_OK or len(p) <= 1 for p in parts)


_STREET = r"(?:STREET|Street|ST\.|ROAD|Road|RD\.?|AVENUE|Avenue|AVE\.?|DRIVE|Drive|DR\.|LANE|Lane|WAY|Way|BOULEVARD|Boulevard|BLVD\.?|PLACE|Place|CRESCENT|Crescent)"
ADDRESS_RX = re.compile(rf"(?<![\w.,-])(\d{{1,5}}[A-Za-z]?\s+(?:[A-Z][A-Za-z'-]+\s+){{1,3}}{_STREET}"
                        rf"(?:[ \t]+(?!NEW\b|TEL\b|FAX\b|PHONE\b)[A-Z][A-Z]{{3,20}}\b)?)")
INTL00_RX = re.compile(r"(?<![\d.])(00[1-9]\d{1,2}[-\s]\d{1,4}[-\s]\d{5,8})(?![\d.])")
COMPANY_UP_RX = re.compile(r"(?<![A-Za-z])((?:[A-Z][A-Z&.-]{1,20}\s+){1,3}(?:DRAUGHTING|DRAFTING|ENGINEERING|DESIGN)"
                           r"\s+(?:SERVICES|LTD\.?|LIMITED|CO\.?))(?![A-Za-z])")
ADV_LIGO_RX = re.compile(r"\b(Advanced LIGO|ADVANCED LIGO|Advanced Ligo)\b")


SHORT_SERIES_RX = re.compile(r"(?<![A-Za-z0-9_.-])([A-Z]{2,3})-(\d{2,3})(?![A-Za-z0-9_-])")
INITIALS_LABEL_RX = re.compile(r"(?:DRAWN|DRN|DRAWN BY|CHECKED|CHK'?D|CHECKED BY|APPROVED|APPV'?D|APP'?D|DESIGNED|DESIGNED BY|"
                               r"DESIGNER|ENG|ENGINEER|DWN|DRW|BY)\s*[:.]?\s+([A-Z]{3})(?![A-Za-z])")
DE_POSTCODE_RX = re.compile(r"(?<![\d.,-])(\d{5}\s+[A-ZÄÖÜ][a-zäöüß]{3,20}(?:-[A-ZÄÖÜ][a-zäöüß]+)?)(?![\w])")
LEGAL_LOWER_RX = re.compile(r"((?:[A-Z][\w&'-]+[ \t]+){1,4}(?:spol\.[ \t]+)?(?:s\.r\.o\.|s\.r\.l\.|S\.r\.l\.|sp\.[ \t]?z[ \t]?o\.o\.|"
                            r"Co\.,?[ \t]?Ltd\.?|Oy|A/S|B\.V\.|GmbH(?:[ \t]&[ \t]Co\.[ \t]KG)?))(?![\w])")
LAB_RX = re.compile(r"\b(LIGO (?:LABORATORY|Laboratory|Lab))\b")
_NOT_INITIALS = {"THE", "AND", "FOR", "MFG", "QTY", "REV", "DWG", "N/A", "TBD", "ALL", "SEE", "PER", "MAT", "DIA", "TYP",
                 "REF", "DATE", "NAME", "ISO", "DIN", "ANSI", "ASME", "CAD", "PDF", "STP", "MAX", "MIN", "NOM", "BOM"}


def series_text(text: str) -> list[tuple[str, str]]:
    """Short project part series in one document: XX-101 ... XX-109 (>=4 distinct numbers, same prefix)."""
    nums: dict[str, set] = {}
    for m in SHORT_SERIES_RX.finditer(text):
        nums.setdefault(m.group(1), set()).add(m.group(2))
    out = []
    for pre, ns in nums.items():
        if len(ns) >= 4 and pre not in _NOT_INITIALS:
            out += [(f"{pre}-{n}", "codefamily") for n in ns]
    return out


def address_text(text: str) -> list[tuple[str, str]]:
    out = []
    for m in ADDRESS_RX.finditer(text):
        words = re.findall(r"[A-Za-z'-]+", m.group(1))[:-1]
        # street name must hold a non-dictionary word (no "3 HOLES ON MAIN ROAD" drawing notes)
        if not re.match(r"\d+x\b", m.group(1)) and \
                any(len(w) >= 4 and w.lower() not in _common_words() and w.lower() not in TECH_STOP
                    and w.lower() not in ("allen", "extruder") for w in words):
            out.append((m.group(1), "address"))
    out += [(m.group(1), "phone") for m in INTL00_RX.finditer(text)]
    for m in DE_POSTCODE_RX.finditer(text):
        city = m.group(1).split()[-1]
        cl = city.lower()
        if cl not in _common_words() and cl.rstrip("s") not in _common_words() and cl not in TECH_STOP:
            out.append((re.sub(r"\s+", " ", m.group(1)), "address"))
    for m in INITIALS_LABEL_RX.finditer(text):
        if m.group(1) not in _NOT_INITIALS and m.group(1).lower() not in _common_words():
            out.append((m.group(1), "person_initials"))
    for m in LEGAL_LOWER_RX.finditer(text):
        ws = re.sub(r"\s+", " ", m.group(1)).split(" ")
        while ws and (ws[0].lower() in _common_words() or ws[0].lower() in STOPWORDS or ws[0].lower() in TECH_STOP):
            ws.pop(0)
        if len(ws) >= 2:
            out.append((" ".join(ws), "company"))
    out += [(m.group(1), "institution") for m in LAB_RX.finditer(text)]
    for m in COMPANY_UP_RX.finditer(text):
        ws = re.sub(r"\s+", " ", m.group(1)).split(" ")
        while ws and (ws[0].lower() in _common_words() or ws[0].lower() in TECH_STOP or ws[0].lower() in STOPWORDS):
            ws.pop(0)
        if len(ws) >= 3:
            out.append((" ".join(ws), "company"))
    out += [(m.group(1), "project") for m in ADV_LIGO_RX.finditer(text)]
    return out


def contacts_text(text: str) -> list[tuple[str, str]]:
    return [(v, k) for v, k in harvest_text(text) if k in ("email", "phone", "url", "domain")] + address_text(text)


FULLNAME_RX = re.compile(r"(?<![\w.])([A-ZÀ-Ý][a-zà-ÿ]{2,14})[ \t]+((?:[A-ZÀ-Ý][a-zà-ÿ]{1,20}[ \t]+)?"
                         r"[A-ZÀ-Ý][a-zà-ÿ]{2,20})(?![\w])")
FIRST_NAMES_ONLY_STOP = {"street", "road", "avenue", "university", "institute", "school", "college", "hall"}


def harvest_text(text: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for m in PROJECT_LABEL_RX.finditer(text):
        v = m.group(1).strip(" .-")
        if len(v) >= 3 and v.lower() not in TECH_STOP and not v.lower().startswith(("name", "no", "number")):
            out.append((v, "project_label"))
    for m in CAMEL_RX.finditer(text):
        w = m.group(1)
        lw = w.lower()
        if 4 <= len(w) <= 24 and len(re.findall(r"[A-Z]", w)) >= 2 and lw not in SOFTWARE_CAMEL \
                and lw not in _common_words() and not _plain_camel(w):
            out.append((w, "project_camel"))
    for m in LIGO_RX.finditer(text):
        out.append((m.group(1), "dwgno"))
    for m in CODECHAIN_RX.finditer(text):
        v = m.group(1)
        if len(v) >= 7 and re.search(r"[A-Z]{2}", v) and not re.fullmatch(r"[\d.\-_]+", v):
            out.append((v, "codechain"))
    for m in INIT_SURNAME_RX.finditer(text):
        sur = re.split(r"\.\s?", m.group(1))[-1].lower()
        if len(sur) >= 3 and sur not in TECH_STOP and sur not in STOPWORDS and sur not in _common_words():
            out.append((m.group(1), "person_init"))
    for m in INSTITUTION_RX.finditer(text):
        v = _clean_name(m.group(1))
        toks = v.split()
        while toks and (toks[0].lower() in TECH_STOP or toks[0].lower() in _common_words()) and \
                not re.fullmatch(_INST, toks[0]):
            toks.pop(0)  # leading drawing words / ordinary words are not part of the name
        v = " ".join(toks)
        if len(toks) >= 2:
            out.append((v, "company"))
    for m in US_PHONE_RX.finditer(text):
        out.append((m.group(1), "phone"))
    for m in DOTTED_PHONE_RX.finditer(text):
        if len(re.sub(r"\D", "", m.group(1))) >= 8:
            out.append((m.group(1), "phone"))
    for m in DWGNO_RX.finditer(text):
        v = m.group(1).strip("-_.")
        if re.search(r"\d", v) and re.search(r"[A-Za-z]", v) and len(re.findall(r"\d", v)) >= 3:
            out.append((v, "dwgno"))
    for m in EMAIL_RX.finditer(text):
        out.append((m.group(0), "email"))
    for m in URL_RX.finditer(text):
        out.append((m.group(1).lower(), "domain"))
    for m in PHONE_RX.finditer(text):
        ph = m.group(0).strip()
        digits = re.sub(r"\D", "", ph)
        if not (8 <= len(digits) <= 15) or re.fullmatch(r"(?:19|20)\d{6}", digits):
            continue
        labelled = re.search(r"(?i)(?:tel|phone|fax|t(?:é|e)l(?:é|e)fono|mobile|mob|cell|tlf)\.?\s*[:.]?\s*$",
                             text[max(0, m.start() - 16):m.start()])
        if (ph.startswith("+") and len(digits) >= 10) or labelled:
            out.append((ph, "phone"))
    for m in LABEL_RX.finditer(text):
        n = _clean_name(m.group(1))
        if n and len(n) >= 3 and n.lower() not in STOPWORDS:
            out.append((n, "person"))
    for m in PERSON_RX.finditer(text):
        for n in _split_people(m.group(1).split()):
            if n.split()[0].lower() in FIRST_NAMES and len(n.split()) >= 2:
                out.append((_clean_name(n), "person"))
    out += _near_label_names(text)
    for m in FULLNAME_RX.finditer(text):
        first, rest = m.group(1), m.group(2).split()
        fl = first.lower()
        if fl in FIRST_NAMES and fl not in _common_words() and \
                all(w.lower() not in TECH_STOP and w.lower() not in STOPWORDS and w.lower() not in FIRST_NAMES_ONLY_STOP
                    and not (GERMAN_SUFFIX.search(w.lower()) and len(w) > 7) for w in rest):
            out.append((first + " " + " ".join(rest), "person_free"))
    for rx in (ORG_RX, ORG_PREFIX_RX):
        for m in rx.finditer(text):
            n = _clean_name(m.group(1))
            if len(n.split()) >= 2:
                out.append((n, "company"))
    for m in PROPERTY_RX.finditer(text):
        n = _clean_name(re.split(r"\.\s|,\s(?:IT|AND)\b", m.group(1))[0])
        if len(n) >= 4:
            out.append((n, "company"))
    return [(v, k) for v, k in out if v]


FAMILY_NUM_RX = re.compile(r"(?<![A-Za-z0-9_.-])([A-Z0-9][A-Z0-9_]{3,15}(?:-[A-Z0-9]{1,8}){0,3})-{1,2}(\d{2,3})(?=[-_ \t\n]|$)")


def family_codes(text: str) -> list[tuple[str, str]]:
    """Parts-list families in one document: (a) upper-case code chains sharing their prefix
    (first two segments) with >=2 other chains, e.g. FD-JL-PCBA-MB / -BB-N / -BB-S;
    (b) a prefix followed by -NN / --NN item numbers >=3 times, e.g. 30DOSTE--01, --02, --03."""
    out: list[tuple[str, str]] = []
    chains = {m.group(1) for m in CODECHAIN_RX.finditer(text)}
    fam: dict[str, set] = {}
    for c in chains:
        segs = re.split(r"[-_.]", c)
        if len(segs) >= 3:
            fam.setdefault("-".join(segs[:2]), set()).add(c)
    for pre, mem in fam.items():
        if len(mem) >= 3 and re.search(r"[A-Z]{2}", pre):
            out += [(m, "codefamily") for m in mem]
    nums: dict[str, set] = {}
    for m in FAMILY_NUM_RX.finditer(text):
        nums.setdefault(m.group(1), set()).add(m.group(2))
    for pre, ns in nums.items():
        if len(ns) >= 3 and re.search(r"[A-Z]{2}", pre):
            out.append((pre, "codefamily"))
    return out


def stem_codes(stem: str, text: str) -> list[tuple[str, str]]:
    """The drawing's own file-name stem (or its code core) printed in its title block."""
    from deid.harvest import part_numbers

    out = []
    low = text.lower()
    for v in {stem} | {c for c, _ in part_numbers(stem)}:
        if len(v) >= 5 and re.search(r"\d", v) and v.lower() in low:
            out.append((v, "dwgno"))
    return out


def harvest(data: bytes, max_pages: int = 6, stem: str = "") -> list[tuple[str, str]]:
    import fitz

    out: list[tuple[str, str]] = []
    try:
        doc = fitz.open(stream=data, filetype="pdf")
    except Exception:
        return out
    try:
        for i, page in enumerate(doc):
            if i >= 40:
                break
            t = page.get_text()
            if i >= max_pages:  # deep pages: contact details only (no name heuristics in long manuals)
                out += contacts_text(t)
                continue
            out += harvest_text(t)
            out += family_codes(t)
            out += address_text(t)
            out += series_text(t)
            if stem:
                out += stem_codes(stem, re.sub(r"\s+", " ", t))
    except Exception:
        pass
    return out


def rewrite(data: bytes, mapper) -> bytes:
    """Replace registered identities in page text; returns original bytes if nothing matched."""
    import fitz

    doc = fitz.open(stream=data, filetype="pdf")
    if doc.needs_pass or doc.is_encrypted:
        return data
    n_pages = doc.page_count
    changed = False
    for page in doc:
        text = page.get_text()
        if not text.strip():
            continue
        raw = text.encode("utf-8", "replace")
        # newline -> space keeps byte positions, so names wrapped over lines still match
        flat = raw.replace(b"\n", b" ").replace(b"\r", b" ").replace(b"\t", b" ")
        hits = mapper.find(flat, "ascii")
        if not hits:
            continue
        placements = []
        seen = set()
        tp = None
        spans = []
        for s, e, key in hits:
            try:
                occ_raw = raw[s:e].decode("utf-8")
                rep = mapper.pseudonym(flat[s:e].decode("utf-8"))
            except (UnicodeError, KeyError):
                continue
            if occ_raw in seen:
                continue
            seen.add(occ_raw)
            # split at line breaks; the same-length pseudonym is split at the same offsets
            parts, pos = [], 0
            for seg in re.split(r"([\r\n\t]+)", occ_raw):
                if seg and not re.fullmatch(r"[\r\n\t]+", seg):
                    parts.append((seg, rep[pos:pos + len(seg)]))
                pos += len(seg)
            if len(parts) > 1:
                parts = [(a.strip(), b.strip()) for a, b in parts if len(a.strip()) >= 3]
            if tp is None:
                tp = page.get_textpage()
                spans = [(fitz.Rect(sp["bbox"]), sp["size"]) for b in page.get_text("dict", textpage=tp)["blocks"]
                         for ln in b.get("lines", []) for sp in ln.get("spans", [])]
            for seg, seg_rep in parts:
                if len(placements) >= MAX_PLACEMENTS:
                    break
                rects = page.search_for(seg, textpage=tp)
                multi = len(rects) > 1 and " " in seg
                wmax = max((r.width for r in rects), default=0)
                for rect in rects:
                    # wrapped pieces are narrower than a full hit; check few-hit cases fully
                    maybe_wrapped = multi and (len(rects) <= 4 or rect.width < 0.85 * wmax)
                    # a hit wrapped over lines comes back as one rect per line:
                    # give each rect only the matching slice of the pseudonym
                    rep_here = seg_rep
                    inside = re.sub(r"\s+", " ", page.get_textbox(rect, textpage=tp)).strip() if maybe_wrapped else ""
                    if inside and inside.lower() != seg.lower():
                        k = seg.lower().find(inside.lower())
                        if k >= 0:
                            rep_here = seg_rep[k:k + len(inside)]
                    size = next((sz for r, sz in spans if r.intersects(rect)), None) or max(4.0, rect.height * 0.8)
                    placements.append((rect, rep_here, size))
                    # redact only the middle band: glyphs of this line cross it, glyphs of
                    # tightly spaced neighbouring lines (dimensions, notes) do not
                    h = rect.height
                    band = fitz.Rect(rect.x0 + 0.5, rect.y0 + 0.35 * h, rect.x1 - 0.5, rect.y1 - 0.35 * h)
                    page.add_redact_annot(band, fill=None, cross_out=False)
        if not placements:
            continue
        page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE,
                              graphics=getattr(fitz, "PDF_REDACT_LINE_ART_NONE", 0),
                              text=getattr(fitz, "PDF_REDACT_TEXT_REMOVE", 0))
        for rect, rep, size in placements:
            # one line, shrunk to the original width, on the original baseline area
            w1 = fitz.get_text_length(rep, fontname="helv", fontsize=1) or 1
            fs = max(2.0, min(size, rect.width / w1 * 0.98))
            page.insert_text((rect.x0, rect.y1 - (rect.height - fs) / 2 - fs * 0.2), rep,
                             fontname="helv", fontsize=fs, color=(0, 0, 0), overlay=True)
        changed = True
    if not changed:
        return data
    out = doc.tobytes(garbage=0, deflate=True)
    chk = fitz.open(stream=out, filetype="pdf")
    if chk.page_count != n_pages:
        raise ValueError("page count changed")
    return out


MAX_PLACEMENTS = 400  # per page; bounds time on dense manuals


def _font_size_at(page, rect) -> float | None:
    try:
        for b in page.get_text("dict", clip=rect)["blocks"]:
            for line in b.get("lines", []):
                for span in line.get("spans", []):
                    return float(span["size"])
    except Exception:
        return None
    return None
