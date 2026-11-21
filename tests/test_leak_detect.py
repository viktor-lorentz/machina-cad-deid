import gzip
import io
import tarfile
import zipfile
import zlib
from collections import Counter

import pikepdf

from deid.detect import Explainer, scan_blob

EX = Explainer(pseudonyms=["kemiru tolavo", "bazodi", "kemiru@bazodi.com"])


def scan(name, data, ex=EX):
    out, samples = Counter(), {}
    scan_blob(name, data, ex, out, samples)
    return out, samples


def test_patterns_raw():
    data = b"contact jane.doe@acme-robotics.com at C:\\Users\\jdoe\\Desktop and /home/alice/x and ACME\\bob\n"
    out, s = scan("notes.txt", data)
    assert out["email"] == 1 and out["path-user"] == 2 and out["domain-account"] == 1
    assert "jdoe" in s["path-user"] and "alice" in s["path-user"]


def test_explained_and_allowlisted():
    data = (b"kemiru@bazodi.com xmlns='http://www.w3.org/2000/svg' C:\\Users\\Public\\x "
            b"/home/runner/work http://bazodi.com/x")
    out, _ = scan("a.svg", data)
    assert sum(out.values()) == 0, out


def test_step_fields():
    step = (b"ISO-10303-21;\nHEADER;\nFILE_NAME('part.stp','2020-01-01',('Jane Doe'),('Acme Robotics'),'p','s','');\n"
            b"ENDSEC;\nDATA;\n#1=PERSON('','Doe','Jane',$,$,$);\n#2=ORGANIZATION('','Acme Robotics','');\n"
            b"#3=PERSON('','Tolavo','Kemiru',$,$,$);\nENDSEC;\nEND-ISO-10303-21;\n")
    out, s = scan("part.stp", step)
    assert out["field:step-author"] == 1 and out["field:step-org"] == 2
    assert out["field:step-person"] == 2  # Doe, Jane; the pseudonym person is explained
    clean = step.replace(b"Jane Doe", b"").replace(b"Acme Robotics", b"Unknown").replace(b"'Doe','Jane'", b"'',''")
    out, _ = scan("part.stp", clean)
    assert sum(out.values()) == 0, out


def test_pdf_author_and_streams():
    pdf = pikepdf.new()
    pdf.add_blank_page()
    pdf.docinfo["/Author"] = "Jane Doe"
    pdf.attachments["notes.txt"] = pikepdf.AttachedFileSpec(pdf, b"mail me: jdoe@acme.org")
    buf = io.BytesIO()
    pdf.save(buf, compress_streams=True)
    out, _ = scan("d.pdf", buf.getvalue())
    assert out["field:pdf-author"] == 1
    assert out["email"] >= 1


def test_nested_containers():
    inner = io.BytesIO()
    with zipfile.ZipFile(inner, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("Document.xml", '<Property name="CreatedBy" type="App::PropertyString"><String value="Jane Doe"/>')
    tbuf = io.BytesIO()
    with tarfile.open(fileobj=tbuf, mode="w") as t:
        payload = inner.getvalue()
        ti = tarfile.TarInfo("model.FCStd")
        ti.size = len(payload)
        t.addfile(ti, io.BytesIO(payload))
    data = gzip.compress(tbuf.getvalue())
    out, s = scan("bundle.tar.gz", data)
    assert out["field:fcstd-CreatedBy"] == 1, (out, s)


def test_zlib_inside_binary():
    blob = b"\x00" * 100 + zlib.compress(b"Author: someone at /home/carol/designs") + b"\x00" * 50
    out, s = scan("part.SLDPRT", blob)
    assert out["path-user"] == 1 and "carol" in s["path-user"]


def test_iges_global():
    g = "1H,,1H;,4Hpart,8Hpart.igs,4HCAD1,4Hv1.0,32,38,6,308,15,4Hpart,1.,1,2HMM,1,0.1,15H20200101.000000,0.001,100.,8HJane Doe,13HAcme Robotics,11,0;"
    lines = []
    for i in range(0, len(g), 72):
        lines.append(g[i:i + 72].ljust(72) + "G" + str(len(lines) + 1).rjust(7))
    data = ("start".ljust(72) + "S      1\n" + "\n".join(lines) + "\n").encode()
    out, s = scan("p.igs", data)
    assert out["field:iges-author"] == 1 and out["field:iges-org"] == 1, (out, s)
    assert s["field:iges-author"] == ["Jane Doe"] and s["field:iges-org"] == ["Acme Robotics"]
    assert sum(out.values()) == 2, out
    clean = data.replace(b"8HJane Doe", b"8HBazodi  ").replace(b"13HAcme Robotics", b"13HKemiru Tolavo")
    out, _ = scan("p.igs", clean)
    assert sum(out.values()) == 0, out


def test_3mf_designer():
    xml = b'<model><metadata name="Designer">Jane Doe</metadata><metadata name="Title">Bracket</metadata></model>'
    out, _ = scan("3D/3dmodel.model", xml)
    assert out["field:3mf-Designer"] == 1
