from deid.vendors import scan_text


def vals(t, src=None):
    return {v for s, v in scan_text(t) if src is None or s == src}


def test_legal_suffix_names():
    t = "Sponsoren: Quorvel Krane GmbH; Zorva GmbH, 51147 Köln Qelt Kontakttechnik GmbH & Co. KG, 32423 Minden."
    v = vals(t, "legal")
    assert {"Quorvel Krane GmbH", "Zorva GmbH", "Qelt Kontakttechnik GmbH & Co. KG"} <= v
    assert not any("Köln" in x for x in v)


def test_labels_trademark_copyright():
    t = "Supplier : Varnquist. Zentrix is the registered trademark of Zentrix, Inc. © Copyright Dec, 2022 Quelbot Tools, Inc. page 1"
    assert "Varnquist" in vals(t, "label")
    assert "Zentrix, Inc" in vals(t, "tm")
    assert "Quelbot Tools, Inc" in vals(t, "copy")


def test_known_vendors_whole_word():
    assert "McMaster" in vals("McMaster [00000A000]", "known")
    assert not vals("Motorcontact wagon", "known")


def test_contact_rows():
    t = "Brazil QX7 sales@qx7.example Czech Republic ZORVA precision, spol. s.r.o. info@zorva.example India Quen Brastow q.brastow@example.org"
    got = set(scan_text(t))
    assert ("contact", "QX7") in got and ("contact", "ZORVA precision, spol. s.r.o.") in got
    assert ("contact-person", "Quen Brastow") in got and ("contact-email", "q.brastow@example.org") in got
