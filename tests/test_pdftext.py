from deid.formats import pdftext


def test_title_block_names_split_and_phone_rules():
    t = ("DRAWN BY: Magnus Kjer   mbokj@mek.dtu.dk\n"
         "Marcos Briones Marcos Cerezo Jon Castillo PROJECTION\nTA00-04-0001 part")
    got = set(pdftext.harvest_text(t))
    assert ("Magnus Kjer", "person") in got
    assert ("Marcos Cerezo", "person") in got and ("Jon Castillo", "person") in got
    assert ("mbokj@mek.dtu.dk", "email") in got
    assert not any(k == "phone" for _, k in got)


def test_rewrite_keeps_line_art_and_pages():
    import fitz
    from deid.registry.pseudonym import Mapper

    doc = fitz.open()
    p = doc.new_page()
    p.draw_line((50, 50), (500, 50))
    p.insert_text((60, 100), "DRAWN BY: Magnus Kjer", fontsize=10)
    data = doc.tobytes()
    m = Mapper()
    m.add("Magnus Kjer", "person")
    out = pdftext.rewrite(data, m)
    d2 = fitz.open(stream=out, filetype="pdf")
    assert "Magnus Kjer" not in d2[0].get_text()
    assert len(d2[0].get_drawings()) >= 1 and d2.page_count == 1


def test_rw_pdf_stream_rewrite_stays_decodable():
    import io
    import pikepdf
    from deid import rewrite as R
    from deid.registry.pseudonym import Mapper

    pdf = pikepdf.new()
    pdf.add_blank_page()
    content = b"BT /F1 12 Tf 72 72 Td (Drawn by Magnus Kjer) Tj ET"
    pdf.pages[0].Contents = pdf.make_stream(content)
    buf = io.BytesIO()
    pdf.save(buf, compress_streams=True)
    m = Mapper()
    m.add("Magnus Kjer", "person")
    out = R.rw_pdf(buf.getvalue(), m)
    p2 = pikepdf.open(io.BytesIO(out))
    data = p2.pages[0].Contents.read_bytes()  # raises if the Flate stream is corrupt
    assert b"Magnus Kjer" not in data and len(data) == len(content)
