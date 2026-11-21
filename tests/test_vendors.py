from deid.vendors import scan_text


def vals(t, src=None):
    return {v for s, v in scan_text(t) if src is None or s == src}


def test_legal_suffix_names():
    t = "Sponsoren: Brunnhuber Krane GmbH; Igus GmbH, 51147 Köln Wago Kontakttechnik GmbH & Co. KG, 32423 Minden."
    v = vals(t, "legal")
    assert {"Brunnhuber Krane GmbH", "Igus GmbH", "Wago Kontakttechnik GmbH & Co. KG"} <= v
    assert not any("Köln" in x for x in v)


def test_labels_trademark_copyright():
    t = "Supplier : Bossard. Xilinx is the registered trademark of Xilinx, Inc. © Copyright Dec, 2022 ShopBot Tools, Inc. page 1"
    assert "Bossard" in vals(t, "label")
    assert "Xilinx, Inc" in vals(t, "tm")
    assert "ShopBot Tools, Inc" in vals(t, "copy")


def test_known_vendors_whole_word():
    assert "McMaster" in vals("McMaster [93330A482]", "known")
    assert not vals("Motorcontact wagon", "known")
