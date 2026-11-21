from deid.consistency import duplicates, references


def test_duplicates_and_references(tmp_path):
    i, o = tmp_path / "in", tmp_path / "out"
    repo = "sources/github/acme__arm"
    (i / repo).mkdir(parents=True)
    (o / repo).mkdir(parents=True)
    (i / repo / "a.stl").write_bytes(b"solid acme\n")
    (i / repo / "b.stl").write_bytes(b"solid acme\n")
    (i / repo / "acme_base.obj").write_bytes(b"mtllib acme_base.mtl\nv 0 0 0\n")
    (i / repo / "acme_base.mtl").write_bytes(b"newmtl x\n")
    (i / repo / "asm.step").write_bytes(b"ref acme_base.obj and acme_base.mtl\n")
    mapping = {f"{repo}/a.stl": f"{repo}/a.stl", f"{repo}/b.stl": f"{repo}/b.stl",
               f"{repo}/acme_base.obj": f"{repo}/bazo_base.obj", f"{repo}/acme_base.mtl": f"{repo}/bazo_base.mtl",
               f"{repo}/asm.step": f"{repo}/asm.step"}
    (o / repo / "a.stl").write_bytes(b"solid bazo\n")
    (o / repo / "b.stl").write_bytes(b"solid kemi\n")  # inconsistent
    (o / repo / "bazo_base.obj").write_bytes(b"mtllib bazo_base.mtl\nv 0 0 0\n")
    (o / repo / "bazo_base.mtl").write_bytes(b"newmtl x\n")
    (o / repo / "asm.step").write_bytes(b"ref bazo_base.obj and acme_base.mtl\n")  # one stale ref
    rels = list(mapping)
    assert duplicates(str(i), str(o), mapping, rels)[:2] == (1, 0)
    checked, ok, bad = references(str(i), str(o), mapping, rels)
    assert (checked, ok) == (3, 2) and bad == [(f"{repo}/asm.step", "bazo_base.mtl")]
