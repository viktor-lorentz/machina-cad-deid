from deid.persons import scan_text


def test_titleblock_people():
    v = lambda t: {x for _, x in scan_text(t)}
    assert "BJD" in v("2 ORIGINAL BJD 11/30/10")
    assert {"ZM", "AK"} <= v("DRAWN APPROVAL REV ZM AK 15/APR/22")
    assert "J.MOSKWA" in v("Designed by J.MOSKWA 07.09.2021")
    assert "David Amigó" in v("Dibujado Comprobado Aprobado David Amigó")
    assert not v("DRAWN BY: NAME DATE") and not v("DESIGNER A SCRIBE")
