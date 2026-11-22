from deid.registry.pseudonym import Mapper


def test_same_identity_same_pseudonym_any_case():
    m = Mapper()
    m.add("BrainCOGS", "account")
    a = m.replace_text("BrainCOGS")
    b = m.replace_text("braincogs")
    assert a.lower() == b and len(a) == 9 and a != "BrainCOGS"
    assert a[0].isupper() and a[5:].isupper()


def test_distinct_identities_stay_distinct():
    m = Mapper()
    out = {m.add(f"company{i:03d}") for i in range(500)}
    assert len(out) == 500


def test_layout_preserved():
    m = Mapper()
    m.add("Jane Doe-42")
    r = m.replace_text("Jane Doe-42")
    assert len(r) == 11 and r[4] == " " and r[8] == "-" and r[9:].isdigit()


def test_word_boundaries():
    m = Mapper()
    m.add("ecto")
    assert m.replace_text("vector ecto_part") .startswith("vector ")
    assert "ecto" not in m.replace_text("vector ecto_part").split(" ")[1]


def test_bytes_ascii_and_utf16_same_length():
    m = Mapper()
    m.add("Jane Doe", "person")
    raw = b"xx Jane Doe yy " + "JANE DOE".encode("utf-16-le") + b"\x00\x00"
    out = m.replace_bytes(raw)
    assert len(out) == len(raw)
    assert b"Jane Doe" not in out and "JANE DOE".encode("utf-16-le") not in out


def test_short_names_never_hang():
    m = Mapper()
    import itertools
    for a, b in itertools.product("abcdefghijklmnopqrstuvwxyz", repeat=2):
        m.add(a + b)
    assert len(m.entries) > 300


def test_compositional_consistency():
    m = Mapper()
    m.add("L. Verhoef", "person")
    m.add("Verhoef", "person")
    m.add("alind@mech.example.org", "email")
    m.add("alind", "account")
    m.add("example.org", "domain")
    assert m.pseudonym("L. Verhoef").split()[-1] == m.pseudonym("Verhoef")
    local, dom = m.pseudonym("alind@mech.example.org").split("@")
    assert local == m.pseudonym("alind") and dom.endswith(m.pseudonym("example.org"))


def test_format_words_never_loaded(tmp_path):
    import json
    from deid.rewrite import load_mappers
    p = tmp_path / "r.json"
    p.write_text(json.dumps({"identities": [{"value": "xmlns", "kind": "company", "scope": "global", "files": 9},
                                            {"value": "Jane Roe", "kind": "person", "scope": "global", "files": 2}]}))
    allm, content = load_mappers(str(p), b"k")
    assert "xmlns" not in content.entries and "jane roe" in content.entries
