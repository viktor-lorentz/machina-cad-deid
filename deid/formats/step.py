"""STEP (ISO 10303-21) handler: harvest identities and rewrite them.

Only single-quoted string literals are touched, so geometry, units and
numeric data are never altered. Software/vendor names (originating system,
preprocessor) are not identities and are left unchanged.
"""

from __future__ import annotations

import re

from deid.registry.pseudonym import Mapper

_STR = re.compile(rb"'((?:[^']|'')*)'")
_FILE_NAME = re.compile(rb"FILE_NAME\s*\((.*?)\)\s*;", re.S)
_ENTITY = re.compile(
    rb"#\d+\s*=\s*(PERSON|ORGANIZATION|PERSON_AND_ORGANIZATION|APPROVAL_PERSON_ORGANIZATION|"
    rb"ADDRESS|POSTAL_ADDRESS|ORGANIZATIONAL_ADDRESS|PERSONAL_ADDRESS)\s*\((.*?)\)\s*;",
    re.S,
)
_VENDOR = re.compile(
    r"solidworks|autodesk|inventor|pro/engineer|ptc|creo|catia|siemens|nx|freecad|"
    r"open ?cascade|opencascade|spatial|acis|step|iso|parasolid|dassault|fusion|"
    r"unknown|none|n/a|undefined",
    re.I,
)


def _lit(b: bytes) -> str:
    return b.decode("latin-1").replace("''", "'")


def _is_candidate(s: str) -> bool:
    s = s.strip()
    return len(s) >= 3 and not _VENDOR.fullmatch(s) and not re.fullmatch(r"[\d\W_]+", s)


def harvest(data: bytes) -> list[tuple[str, str]]:
    """Return (string, kind) identity candidates found in a STEP file."""
    out: list[tuple[str, str]] = []
    head = data[:20000]
    m = _FILE_NAME.search(head)
    if m:
        lits = [_lit(x) for x in _STR.findall(m.group(1))]
        # name, timestamp, author(s), organization(s), preprocessor, system, authorization
        if len(lits) >= 4:
            for a in lits[2:3]:
                if _is_candidate(a):
                    out.append((a, "person"))
            for o in lits[3:4]:
                if _is_candidate(o):
                    out.append((o, "company"))
        if len(lits) >= 7 and _is_candidate(lits[6]):
            out.append((lits[6], "person"))
    for em in _ENTITY.finditer(data):
        kind = "company" if b"ORGANIZATION" in em.group(1) and b"PERSON" not in em.group(1) else "person"
        for lit in _STR.findall(em.group(2)):
            s = _lit(lit)
            if _is_candidate(s) and not re.fullmatch(r"[A-Za-z0-9_]{1,3}", s):
                out.append((s, kind))
    return out


def rewrite(data: bytes, mapper: Mapper) -> bytes:
    """Replace registered identities inside string literals only."""
    def sub(m: re.Match) -> bytes:
        text = _lit(m.group(1))
        new = mapper.replace_text(text)
        if new == text:
            return m.group(0)
        return b"'" + new.replace("'", "''").encode("latin-1", "replace") + b"'"

    return _STR.sub(sub, data)
