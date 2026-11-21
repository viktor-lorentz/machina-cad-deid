import io
import struct
import zipfile

import pikepdf

from deid.fingerprint import fingerprint

STEP = (b"ISO-10303-21;\nHEADER;\nFILE_NAME('a.stp','t',('Jane Doe'),('Acme'),'p','s','');\nENDSEC;\nDATA;\n"
        b"#1=PRODUCT('Acme bracket','Acme bracket','',(#2));\n#3=CARTESIAN_POINT('',(0.,1.5,2.));\nENDSEC;\nEND-ISO-10303-21;\n")


def same(a, b, ext):
    return fingerprint(a, ext) == fingerprint(b, ext)


def test_step_strings_masked_geometry_kept():
    renamed = STEP.replace(b"Jane Doe", b"Kemi Tol").replace(b"Acme", b"Bazo")
    assert same(STEP, renamed, "stp")
    assert not same(STEP, STEP.replace(b"1.5", b"1.6"), "stp")
    assert not same(STEP, STEP.replace(b"(#2)", b"(#3)"), "stp")


def test_stl_binary():
    tri = struct.pack("<12fH", *([0.0] * 3 + [1.0, 2.0, 3.0] * 3), 0)
    a = b"solid Jane Doe".ljust(80, b" ") + struct.pack("<I", 1) + tri
    b = b"solid Kemi Tol".ljust(80, b" ") + struct.pack("<I", 1) + tri
    assert same(a, b, "stl")
    c = a[:-10] + b"\x01" + a[-9:]
    assert not same(a, c, "stl")


def test_iges_hollerith_masked():
    p1 = b"406,2,8HJane Doe,1.5;".ljust(64) + b"       1P      1\n"
    p2 = b"406,2,8HKemi Tol,1.5;".ljust(64) + b"       1P      1\n"
    p3 = b"406,2,8HKemi Tol,1.6;".ljust(64) + b"       1P      1\n"
    d = b"     406       1       0       0       0       0       0       000000000D      1\n"
    assert same(d + p1, d + p2, "igs")
    assert not same(d + p1, d + p3, "igs")


def test_dxf_text_masked_coords_kept():
    a = b"0\nTEXT\n8\nTITLE\n10\n1.0\n20\n2.0\n1\nDrawn by Jane Doe\n0\nEOF\n"
    b = a.replace(b"Jane Doe", b"Kemi Tol")
    c = a.replace(b"10\n1.0", b"10\n1.1")
    assert same(a, b, "dxf") and not same(a, c, "dxf")


def test_pdf_pages_and_boxes():
    def mk(n, w=612):
        p = pikepdf.new()
        for _ in range(n):
            p.add_blank_page(page_size=(w, 792))
        buf = io.BytesIO()
        p.save(buf)
        return buf.getvalue()
    assert same(mk(2), mk(2), "pdf")
    assert not same(mk(2), mk(3), "pdf")
    assert not same(mk(2), mk(2, 595), "pdf")


def test_zip_recurses_into_members():
    def mk(step, name):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr(name, step)
        return buf.getvalue()
    renamed = STEP.replace(b"Jane Doe", b"Kemi Tol")
    assert same(mk(STEP, "jane/a.stp"), mk(renamed, "kemi/a.stp"), "zip")
    assert not same(mk(STEP, "a.stp"), mk(STEP.replace(b"1.5", b"9.9"), "a.stp"), "zip")
