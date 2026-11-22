from deid.formats import pdftext


def test_title_block_names_split_and_phone_rules():
    t = ("DRAWN BY: Anna Lindqvist   alind@mech.example.org\n"
         "Pablo Ortega Pablo Serrano John Varela PROJECTION\nTA00-04-0001 part")
    got = set(pdftext.harvest_text(t))
    assert ("Anna Lindqvist", "person") in got
    assert ("Pablo Serrano", "person") in got and ("John Varela", "person") in got
    assert ("alind@mech.example.org", "email") in got
    assert not any(k == "phone" for _, k in got)


def test_rewrite_keeps_line_art_and_pages():
    import fitz
    from deid.registry.pseudonym import Mapper

    doc = fitz.open()
    p = doc.new_page()
    p.draw_line((50, 50), (500, 50))
    p.insert_text((60, 100), "DRAWN BY: Anna Lindqvist", fontsize=10)
    data = doc.tobytes()
    m = Mapper()
    m.add("Anna Lindqvist", "person")
    out = pdftext.rewrite(data, m)
    d2 = fitz.open(stream=out, filetype="pdf")
    assert "Anna Lindqvist" not in d2[0].get_text()
    assert len(d2[0].get_drawings()) >= 1 and d2.page_count == 1


def test_rw_pdf_stream_rewrite_stays_decodable():
    import io
    import pikepdf
    from deid import rewrite as R
    from deid.registry.pseudonym import Mapper

    pdf = pikepdf.new()
    pdf.add_blank_page()
    content = b"BT /F1 12 Tf 72 72 Td (Drawn by Anna Lindqvist) Tj ET"
    pdf.pages[0].Contents = pdf.make_stream(content)
    buf = io.BytesIO()
    pdf.save(buf, compress_streams=True)
    m = Mapper()
    m.add("Anna Lindqvist", "person")
    out = R.rw_pdf(buf.getvalue(), m)
    p2 = pikepdf.open(io.BytesIO(out))
    data = p2.pages[0].Contents.read_bytes()  # raises if the Flate stream is corrupt
    assert b"Anna Lindqvist" not in data and len(data) == len(content)


def test_redaction_spares_tightly_spaced_neighbour_lines():
    import fitz
    from deid.registry.pseudonym import Mapper

    doc = fitz.open()
    p = doc.new_page()
    p.insert_text((60, 100), "PROPERTY OF HOWARD HUGHES", fontsize=9)
    p.insert_text((60, 111), "MEDICAL INSTITUTE. IT SHALL", fontsize=9)
    p.insert_text((60, 121), "12.50 DRAWN Anna Lindqvist 7.25", fontsize=9)
    p.insert_text((60, 130), "3.175 4.40 9.99", fontsize=9)
    m = Mapper()
    m.add("HOWARD HUGHES MEDICAL INSTITUTE", "company")
    m.add("Anna Lindqvist", "person")
    t = fitz.open(stream=pdftext.rewrite(doc.tobytes(), m), filetype="pdf")[0].get_text()
    for keep in ("PROPERTY OF", "IT SHALL", "12.50", "7.25", "3.175", "4.40", "9.99"):
        assert keep in t
    assert "HOWARD" not in t and "Magnus" not in t
    assert m.pseudonym("Anna Lindqvist") in t


def test_oleps_field_rewrite_cp1252_same_length():
    import struct
    import uuid
    from deid.formats import oleps
    from deid.registry.pseudonym import Mapper

    # minimal SummaryInformation property set: codepage 1252 + author "Séba"
    val = "Séba".encode("cp1252") + b"\x00"
    props = [(1, struct.pack("<IH2x", 2, 1252)), (4, struct.pack("<II", 30, len(val)) + val + b"\x00" * (-len(val) % 4))]
    hdr_len = 8 + 8 * len(props)
    offs, blob = [], b""
    for pid, data in props:
        offs.append((pid, hdr_len + len(blob)))
        blob += data
    section = struct.pack("<II", hdr_len + len(blob), len(props)) + b"".join(struct.pack("<II", p, o) for p, o in offs) + blob
    body = struct.pack("<HHI16sI", 0xFFFE, 0, 0, b"\x00" * 16, 1) + uuid.UUID(oleps.SUMMARY).bytes_le + struct.pack("<I", 48) + section
    m = Mapper()
    m.add("Séba", "account")
    out = oleps.rewrite_fields(body, m)
    assert len(out) == len(body) and out != body
    assert [v for _, pid, v in oleps.parse(out) if pid == 4] == [m.pseudonym("Séba")]
