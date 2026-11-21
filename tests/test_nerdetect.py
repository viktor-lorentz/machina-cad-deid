import importlib


def test_detect_from_cache_maps_offsets(tmp_path, monkeypatch):
    monkeypatch.setenv("DEID_NER_CACHE", str(tmp_path / "c.sqlite"))
    import deid.nerdetect as nd
    nd = importlib.reload(nd)
    text = "DRAWN BY   Jane   Doe\n\nACME  Widgets Ltd, 12 Main St\n42\n"
    n1, _ = nd._norm("DRAWN BY   Jane   Doe")
    n2, _ = nd._norm("ACME  Widgets Ltd, 12 Main St")
    assert n1 == "DRAWN BY Jane Doe"
    nd.cache_put({nd.key(n1): [[9, 17, "person", 0.9]],
                  nd.key(n2): [[0, 16, "company", 0.8], [18, 29, "address", 0.3]]})
    spans = nd.detect(text, filter=False, run_missing=False)
    got = [(text[s:e], k) for s, e, k in spans]
    assert got == [("Jane   Doe", "person"), ("ACME  Widgets Ltd", "company")]   # address below threshold
    assert nd.detect("", run_missing=False) == [] and nd.detect("12 34\n", run_missing=False) == []


def test_pack_respects_model_window():
    import deid.nerdetect as nd
    lines = ["word " * 100] * 10
    for text, members in nd._pack([l.strip() for l in lines]):
        assert len(nd._GTOK.findall(text)) <= nd.MAX_LEN
