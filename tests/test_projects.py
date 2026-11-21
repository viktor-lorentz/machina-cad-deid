import deid.projects as P


def test_repo_candidates_and_spans():
    P.WORDS = {"bento", "arm", "measure", "plus"}
    assert {"bento arm", "cosi"} <= P.repo_candidates("Bento-Arm-Hardware") | P.repo_candidates("cosi-measure")
    assert P.repo_candidates("OPEN-SOURCE-LARGE-FORMAT-CNC-MACHINE-3D-PRINTER") == set()
    c = P.repo_candidates("BCN3D-Moveo")
    t = "the BCN3D Moveo arm, Bento-Arm"
    got = {t[s:e] for g, s, e, _, _ in P.ngrams_with_spans(t) if g in c}
    assert "BCN3D Moveo" in got


def test_labels():
    t = "Project: PrinterStand_v2, Mikromakromint-Projekt: x. Project : unnamed"
    assert [m.group(1) for m in P.LABEL.finditer(t)][0] == "PrinterStand_v2"
    assert "Mikromakromint" in [m.group(1) for m in P.LABEL2.finditer(t)]
