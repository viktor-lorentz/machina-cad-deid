from deid.codes import scan_text


def test_codes_hosts_addresses():
    t = ("ITEM PART NO. QTY QZ-001 DIN-6885 ISO-4017 M8x1,25 6061-T6 R5.13 6-32 QXVLTRN8 QZ-XV-PCBA-MB 0.0.917.04 v2.1 2021 "
         "see www.qelvorn-zx.com http://www.w3.org/2000 Zorva GmbH, 51147 Köln Qelt")
    got = scan_text(t)
    codes = {v for k, v in got if k == "code"}
    assert {"QZ-001", "QXVLTRN8", "QZ-XV-PCBA-MB", "0.0.917.04"} <= codes
    assert not codes & {"DIN-6885", "ISO-4017", "M8x1,25", "6061-T6", "R5.13", "6-32", "v2.1", "2021"}
    assert ("host", "www.qelvorn-zx.com") in got and not any("w3.org" in v for k, v in got)
    assert ("address", "51147 Köln") in got
