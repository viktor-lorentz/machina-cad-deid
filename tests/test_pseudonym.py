from deid.registry.pseudonym import Mapper


def test_same_identity_same_pseudonym_case_insensitive():
    m = Mapper()
    a = m.natural("Acme Robotics", "company")
    assert m.natural("ACME ROBOTICS", "company").lower() == a.lower()
    assert m.natural("acme  robotics", "company").lower() == a.lower()


def test_distinct_identities_stay_distinct():
    m = Mapper()
    names = [f"Company {i}" for i in range(500)]
    out = {m.add(n, "company").casefold() for n in names}
    assert len(out) == 500


def test_samelen_preserves_length_and_classes():
    m = Mapper()
    s = "John_Smith-42"
    r = m.samelen(s)
    assert len(r) == len(s) and r != s
    assert r[4] == "_" and r[10] == "-"
    assert r[:4].isalpha() and r[-2:].isdigit()
    assert m.samelen(s) == r


def test_replace_text_and_bytes():
    m = Mapper()
    m.add("Jane Doe", "person")
    assert "Jane Doe" not in m.replace_text("author: Jane Doe, jane doe")
    raw = b"xx Jane Doe yy " + "Jane Doe".encode("utf-16-le")
    out = m.replace_bytes(raw)
    assert len(out) == len(raw) and b"Jane Doe" not in out
