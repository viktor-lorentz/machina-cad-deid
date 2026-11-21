from deid.inline import page_spans


def test_inline_rules():
    v = lambda t: {x for _, x in page_spans(t)}
    assert {"Taylor", "Moore", "Armstrong"} <= v("Relays and SSRs Taylor, Moore, and Armstrong 24 Sep 2024")
    assert "Nikita" in v("Heat sink element. Nikita 02/06/2022 Designed by Checked by Approved by Date")
    assert {"ZM", "AK"} <= v("DRAWN APPROVAL REV ZM AK 15/APR/22")
    assert "Smith" in v("as shown by Smith et al. in 2019")
    assert not v("Steel, Aluminium, and Brass parts; Nuts and Bolts")
