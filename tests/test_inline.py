from deid.inline import page_spans

# synthetic values only (public repo): no corpus identifiers in tests or comments


def test_inline_rules():
    v = lambda t: {x for _, x in page_spans(t)}
    assert {"Quorvel", "Brastin", "Ylandor"} <= v("Relays and SSRs Quorvel, Brastin, and Ylandor 24 Sep 2024")
    assert "Zentaro" in v("Heat sink element. Zentaro 02/06/2022 Designed by Checked by Approved by Date")
    assert {"QX", "VB"} <= v("DRAWN APPROVAL REV QX VB 15/APR/22")
    assert "Morvadel" in v("as shown by Morvadel et al. in 2019")
    assert not v("Steel, Aluminium, and Brass parts; Nuts and Bolts")


def test_contact_rules():
    v = set(page_spans("PHONE: 0099 01 2345678. MOB: 0123456789 E-MAIL: a@example.org Qel qel@lab.zqx.example ZQX LAB DRAWN Doc ID 004417 Rev 2"))
    assert ("phone", "0123456789") in v and ("company", "ZQX LAB") in v and ("part", "004417") in v
