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
""".split())

LABELS = (r"drawn(?:\s+by)?|dwn|drn|checked(?:\s+by)?|chk|chkd|approved(?:\s+by)?|appr?|designed(?:\s+by)?|"
          r"designer|design|engineer|eng|author|created\s+by|creator|made\s+by|prepared\s+by|reviewed\s+by|"
          r"name|gezeichnet|gezeich\.|gepr(?:ü|ue)ft|bearbeitet|bearb\.|konstrukteur|ersteller|norm|"
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
             "mass", "units", "page", "file", "angular", "general", "surface", "general", "standard", "type",
             "model", "design", "designed", "engineer", "approval", "manufacturer", "supplier", "project"}


def _clean_name(s: str) -> str:
    toks = s.strip(" .,;:-").split()
    while toks and toks[-1].lower().strip(".:") in STOPWORDS:
        toks.pop()
    while toks and toks[0].lower().strip(".:") in STOPWORDS:
        toks.pop(0)
    return " ".join(toks)


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


def harvest_text(text: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
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


def harvest(data: bytes, max_pages: int = 6) -> list[tuple[str, str]]:
    import fitz

    out: list[tuple[str, str]] = []
    try:
        doc = fitz.open(stream=data, filetype="pdf")
    except Exception:
        return out
    try:
        for i, page in enumerate(doc):
            if i >= max_pages:
                break
            out += harvest_text(page.get_text())
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
        hits = mapper.find(text.encode("utf-8", "replace"), "ascii")
        if not hits:
            continue
        raw = text.encode("utf-8", "replace")
        seen = set()
        for s, e, key in hits:
            occ = raw[s:e].decode("utf-8", "replace")
            if occ in seen:
                continue
            seen.add(occ)
            rep = mapper.pseudonym(occ)
            for quad in page.search_for(occ, quads=False):
                size = _font_size_at(page, quad) or max(4.0, quad.height * 0.8)
                page.add_redact_annot(quad, text=rep, fontname="helv", fontsize=size * 0.92,
                                      fill=None, text_color=(0, 0, 0), cross_out=False)
                changed = True
        if changed:
            page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE,
                                  graphics=getattr(fitz, "PDF_REDACT_LINE_ART_NONE", 0),
                                  text=getattr(fitz, "PDF_REDACT_TEXT_REMOVE", 0))
    if not changed:
        return data
    out = doc.tobytes(garbage=0, deflate=True)
    chk = fitz.open(stream=out, filetype="pdf")
    if chk.page_count != n_pages:
        raise ValueError("page count changed")
    return out


def _font_size_at(page, rect) -> float | None:
    try:
        for b in page.get_text("dict", clip=rect)["blocks"]:
            for line in b.get("lines", []):
                for span in line.get("spans", []):
                    return float(span["size"])
    except Exception:
        return None
    return None
