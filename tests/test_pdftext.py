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
