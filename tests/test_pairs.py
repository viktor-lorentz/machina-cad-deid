from deid import rewrite as R
from deid.registry.pseudonym import Mapper


def _setup(native):
    m = Mapper(secret=b"x")
    m.add("J003121", "part")
    m.add("D060491", "part")
    c = Mapper(secret=b"x")
    for k in m.entries:
        c.entries[k] = m.entries[k]
        c.kinds[k] = m.kinds[k]
    R.G.update(allm=m, content=c, pathm=R.path_mapper(c), native_stems=R.native_stems(native))
    return m


def test_part_stem_renamed_like_drawing_text():
    m = _setup(["a/D060491.SLDPRT"])
    a = R.map_path("sources/x/y/J003121.pdf", m, R.G["pathm"], True)
    b = R.map_path("sources/x/y/J003121.STEP", m, R.G["pathm"], True)
    assert a.rsplit(".", 1)[0] == b.rsplit(".", 1)[0] != "sources/x/y/J003121"
    assert a.endswith(m.pseudonym("J003121") + ".pdf")


def test_native_stem_kept():
    m = _setup(["a/D060491.SLDPRT"])
    assert R.map_path("sources/x/y/D060491.pdf", m, R.G["pathm"], True) == "sources/x/y/D060491.pdf"


def test_step_multiline_string():
    m = _setup([])
    d = b"FILE_NAME('C:\\\\A\\\\\nJ003121.stp','x');\n#1=PRODUCT('J003121','','',(#2));\n"
    assert b"J003121" not in R.rw_step(d, m)


def test_native_file_keeps_part_refs_but_not_people():
    m = _setup([])
    m.add("Smith", "person")
    c = R.G["content"]
    for k in m.entries:
        c.entries[k] = m.entries[k]
        c.kinds[k] = m.kinds[k]
    R.G["pathm"] = R.path_mapper(c)
    body = b"ref C:\\Users\\Smith\\J003121.SLDPRT end"
    out = R.rewrite_bytes("a/x.SLDDRW", body, c)
    assert b"J003121.SLDPRT" in out and b"Smith" not in out
    assert b"J003121" not in R.rewrite_bytes("a/x.txt", body, c)
