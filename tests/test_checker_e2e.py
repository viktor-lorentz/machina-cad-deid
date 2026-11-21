import hashlib
import json
import os

from deid import checker, leakscan, rewrite


def _held_out_repo(prefix):
    i = 0
    while True:
        name = f"{prefix}{i}__bracket"
        if checker.held_out(f"sources/github/{name}/x"):
            return name
        i += 1


def test_rewrite_then_check(tmp_path, capsys):
    inp, out = tmp_path / "input", tmp_path / "run" / "corpus"
    repo = _held_out_repo("janedoe")
    d = inp / "sources" / "github" / repo
    d.mkdir(parents=True)
    (d / "part.stp").write_bytes(
        b"ISO-10303-21;\nHEADER;\nFILE_NAME('part.stp','2020-01-01',('Jane Doe'),('Acme Robotics'),'p','s','');\n"
        b"ENDSEC;\nDATA;\n#1=CARTESIAN_POINT('',(0.,1.5,2.));\nENDSEC;\nEND-ISO-10303-21;\n")
    (d / "notes.txt").write_bytes(b"designed by Jane Doe, questions to x.y@secretcorp.com\n")
    reg = tmp_path / "registry.json"
    owner = repo.split("__")[0]
    reg.write_text(json.dumps({"identities": [
        {"value": "Jane Doe", "kind": "person", "scope": "global"},
        {"value": "Acme Robotics", "kind": "company", "scope": "global"},
        {"value": owner, "kind": "account", "scope": "global"},
    ]}))
    secret = b"test-secret"
    rewrite.run(str(inp), str(out), str(reg), secret, {"rename": True, "archives": True}, workers=2)
    results = tmp_path / "run" / "rewrite-results.json"
    r = checker.run(str(inp), str(out), str(results), str(reg), secret, n=100, workers=2)
    assert r["found"] == 1.0 and r["usable"] == 1.0
    assert r["deid"] == 1.0          # every registry identity was replaced
    assert r["deid_strict"] == 0.5   # but notes.txt still has an e-mail the registry never knew
    leakscan.run(str(out), str(reg), secret, workers=2)
    err = capsys.readouterr().err
    assert "email" in err and "x.y@secretcorp.com" in err


def test_pdfcheck_pair(tmp_path):
    import fitz

    from deid import pdfcheck
    from deid.registry.pseudonym import Mapper

    m = Mapper(secret=b"s")
    m.add("Jane Doe", "person")
    pseudo = m.pseudonym("Jane Doe")

    def mk(path, text):
        d = fitz.open()
        d.new_page().insert_text((72, 72), text)
        d.save(path)

    mk(tmp_path / "a.pdf", "Drawn by Jane Doe")
    mk(tmp_path / "good.pdf", f"Drawn by {pseudo}")
    mk(tmp_path / "bad.pdf", "Drawn by Jane Doe")
    g = pdfcheck.check_pair(str(tmp_path / "a.pdf"), str(tmp_path / "good.pdf"), m)
    b = pdfcheck.check_pair(str(tmp_path / "a.pdf"), str(tmp_path / "bad.pdf"), m)
    assert (g["occ"], g["removed"], g["consistent"]) == (1, 1, 1)
    assert (b["occ"], b["removed"], b["consistent"]) == (1, 0, 0)
