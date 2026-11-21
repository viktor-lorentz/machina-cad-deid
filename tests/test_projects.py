import deid.projects as P


def test_repo_candidates_and_spans():
    P.WORDS = {"zarvo", "arm", "measure", "plus"}
    assert {"zarvo arm", "qelt"} <= P.repo_candidates("Zarvo-Arm-Hardware") | P.repo_candidates("qelt-measure")
    assert P.repo_candidates("OPEN-SOURCE-LARGE-FORMAT-CNC-MACHINE-3D-PRINTER") == set()
    c = P.repo_candidates("QX5D-Vorlo")
    t = "the QX5D Vorlo arm, Zarvo-Arm"
    got = {t[s:e] for g, s, e, _, _ in P.ngrams_with_spans(t) if g in c}
    assert "QX5D Vorlo" in got


def test_labels():
    t = "Project: QuelStand_v2, Zorvaplentrix-Projekt: x. Project : unnamed"
    assert [m.group(1) for m in P.LABEL.finditer(t)][0] == "QuelStand_v2"
    assert "Zorvaplentrix" in [m.group(1) for m in P.LABEL2.finditer(t)]
