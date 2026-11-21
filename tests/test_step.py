from deid.formats import step
from deid.registry.pseudonym import Mapper

SAMPLE = b"""ISO-10303-21;
HEADER;
FILE_DESCRIPTION(('part by Jane Doe'),'2;1');
FILE_NAME('housing.step','2020-01-01T',('Jane Doe'),('Acme Robotics Inc'),
'SolidWorks 2018','SolidWorks 2018','');
ENDSEC;
DATA;
#1=CARTESIAN_POINT('',(1.5,2.5,3.5));
#2=ORGANIZATION('ACME','Acme Robotics Inc','');
#3=PERSON('1','Doe','Jane',$,$,$);
ENDSEC;
END-ISO-10303-21;
"""


def test_harvest_finds_author_and_org_not_vendor():
    found = dict(step.harvest(SAMPLE))
    assert found["Jane Doe"] == "person"
    assert found["Acme Robotics Inc"] == "company"
    assert "SolidWorks 2018" not in found


def test_rewrite_changes_identity_only():
    m = Mapper()
    for s, k in step.harvest(SAMPLE):
        m.add(s, k)
    out = step.rewrite(SAMPLE, m)
    assert b"Jane Doe" not in out and b"Acme Robotics Inc" not in out
    assert b"(1.5,2.5,3.5)" in out and b"SolidWorks 2018" in out
