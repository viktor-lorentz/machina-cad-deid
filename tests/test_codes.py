from deid.codes import scan_text


def test_codes_hosts_addresses():
    t = ("ITEM PART NO. QTY FC-001 DIN-6885 ISO-4017 M8x1,25 6061-T6 R5.13 6-32 HBLFSNT8 FD-JL-PCBA-MB 0.0.026.03 v2.1 2021 "
         "see www.spatial.com http://www.w3.org/2000 Igus GmbH, 51147 Köln Wago")
    got = scan_text(t)
    codes = {v for k, v in got if k == "code"}
    assert {"FC-001", "HBLFSNT8", "FD-JL-PCBA-MB", "0.0.026.03"} <= codes
    assert not codes & {"DIN-6885", "ISO-4017", "M8x1,25", "6061-T6", "R5.13", "6-32", "v2.1", "2021"}
    assert ("host", "www.spatial.com") in got and not any("w3.org" in v for k, v in got)
    assert ("address", "51147 Köln") in got
