import fitz

from deid import pdfeval
from deid.registry.pseudonym import Mapper


def _mk(path, lines):
    d = fitz.open()
    p = d.new_page()
    for i, t in enumerate(lines):
        p.insert_text((72, 72 + 14 * i), t)
    d.save(path)


def test_eval_pdf_categories(tmp_path):
    m = Mapper(secret=b"s")
    m.add("Jane Doe", "person")
    m.add("Acme Robotics", "company")
    pdfeval.G["m"] = m
    pdfeval.G["ptok"] = set()
    pj, pa = m.pseudonym("Jane Doe"), m.pseudonym("Acme Robotics")
    src = tmp_path / "in.pdf"
    _mk(src, ["Drawn by Jane Doe", "Material steel 304", "Acme Robotics bracket"])
    good = tmp_path / "good.pdf"
    _mk(good, [f"Drawn by {pj}", "Material steel 304", f"{pa} bracket"])
    r, f, o = pdfeval.eval_pdf(str(src), str(good), "good.pdf")
    assert (r["occ"], r["removed"], r["consistent"], r["scope_viol"], r["leak"]) == (2, 2, 2, 0, 0), (r, f)
    # over-redaction (material changed), leak (Acme kept), inconsistent (wrong pseudonym)
    bad = tmp_path / "bad.pdf"
    _mk(bad, ["Drawn by Zuzu Kaka", "Material XXXXX 304", "Acme Robotics bracket"])
    r, f, o = pdfeval.eval_pdf(str(src), str(bad), "bad.pdf")
    kinds = sorted(x[0] for x in f)
    assert kinds == ["leak", "no-pseudonym", "scope-change"], f
    assert r["removed"] == 1 and r["consistent"] == 0 and r["leak"] == 1
