from deid.persons import scan_text


def test_titleblock_people():
    v = lambda t: {x for _, x in scan_text(t)}
    assert "QVX" in v("2 ORIGINAL QVX 11/30/10")
    assert {"QX", "VB"} <= v("DRAWN APPROVAL REV QX VB 15/APR/22")
    assert "J.ZORVEK" in v("Designed by J.ZORVEK 07.09.2021")
    assert "Darel Quinó" in v("Dibujado Comprobado Aprobado Darel Quinó")
    assert not v("DRAWN BY: NAME DATE") and not v("DESIGNER A SCRIBE")
