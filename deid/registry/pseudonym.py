"""Deterministic, collision-free pseudonyms and a global replacement mapper.

One Mapper instance holds every identity found in the corpus. The same
original string always yields the same pseudonym; different identities stay
distinct. Two flavours exist:

* natural(): readable replacement of any length, for text formats.
* samelen(): replacement with exactly the same number of characters, keeping
  character classes (upper/lower/digit/punctuation), for binary formats where
  byte offsets must not shift.
"""

from __future__ import annotations

import hashlib
import hmac
import re
from dataclasses import dataclass, field

_FIRST = ["Alder", "Birch", "Cedar", "Dune", "Ember", "Flint", "Grove", "Harbor",
          "Iris", "Juniper", "Kestrel", "Lumen", "Maple", "Nova", "Onyx", "Pine",
          "Quartz", "Raven", "Sable", "Tundra", "Umber", "Vale", "Willow", "Zephyr"]
_SECOND = ["Works", "Labs", "Dynamics", "Systems", "Robotics", "Design", "Forge",
           "Machines", "Tech", "Industries", "Studio", "Engineering"]
_PEOPLE_F = ["Alex", "Blake", "Casey", "Drew", "Emery", "Finley", "Gray", "Harper",
             "Indy", "Jordan", "Kai", "Logan", "Morgan", "Noel", "Parker", "Quinn",
             "Riley", "Sage", "Taylor", "Wren"]
_PEOPLE_L = ["Ashford", "Bellamy", "Carver", "Dalton", "Ellis", "Fenwick", "Garland",
             "Hollis", "Ingram", "Jarvis", "Kendall", "Lowell", "Mercer", "Nash",
             "Osborne", "Prescott", "Quincy", "Rowan", "Sutton", "Thatcher"]

_UP = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
_LO = "abcdefghijklmnopqrstuvwxyz"
_DG = "0123456789"


def norm(s: str) -> str:
    """Normalized identity key: case-folded, whitespace collapsed."""
    return re.sub(r"\s+", " ", s.strip()).casefold()


def _digest(secret: bytes, kind: str, key: str, salt: int = 0) -> bytes:
    return hmac.new(secret, f"{kind}|{key}|{salt}".encode(), hashlib.sha256).digest()


def _case_like(orig: str, new: str) -> str:
    if orig.isupper():
        return new.upper()
    if orig.islower():
        return new.lower()
    return new


@dataclass
class Mapper:
    secret: bytes = b"machina-deid-default-secret"
    # norm(original) -> (kind, pseudonym_natural)
    entries: dict[str, tuple[str, str]] = field(default_factory=dict)
    _used: set[str] = field(default_factory=set)
    _regex: re.Pattern | None = None

    # -- registration ------------------------------------------------------
    def add(self, original: str, kind: str = "name") -> str:
        key = norm(original)
        if not key:
            return original
        if key in self.entries:
            return self.entries[key][1]
        salt = 0
        while True:
            cand = self._natural(kind, key, salt)
            if norm(cand) not in self._used and norm(cand) != key:
                break
            salt += 1
        self._used.add(norm(cand))
        self.entries[key] = (kind, cand)
        self._regex = None
        return cand

    def _natural(self, kind: str, key: str, salt: int) -> str:
        d = _digest(self.secret, kind, key, salt)
        n = int.from_bytes(d[:8], "big")
        if kind == "person":
            return f"{_PEOPLE_F[n % len(_PEOPLE_F)]} {_PEOPLE_L[(n >> 8) % len(_PEOPLE_L)]}{(n >> 16) % 97 if salt else ''}"
        if kind == "email":
            return f"user{n % 100000:05d}@example.invalid"
        if kind == "domain":
            return f"{_FIRST[n % len(_FIRST)].lower()}{(n >> 8) % 1000:03d}.example.invalid"
        if kind == "account":
            return f"{_FIRST[n % len(_FIRST)].lower()}-{_SECOND[(n >> 8) % len(_SECOND)].lower()}-{(n >> 16) % 1000:03d}"
        # company / project / part / generic
        return f"{_FIRST[n % len(_FIRST)]} {_SECOND[(n >> 8) % len(_SECOND)]}{(n >> 16) % 97 if salt else ''}"

    # -- pseudonyms --------------------------------------------------------
    def natural(self, original: str, kind: str = "name") -> str:
        """Readable pseudonym, any length. Registers the identity if new."""
        return _case_like(original, self.add(original, kind))

    def samelen(self, original: str) -> str:
        """Pseudonym with identical length and per-character class."""
        key = norm(original)
        d = _digest(self.secret, "samelen", key)
        out = []
        stream = d
        i = 0
        for ch in original:
            if i >= len(stream):
                stream = hashlib.sha256(stream).digest()
                i = 0
            b = stream[i]
            i += 1
            if ch in _UP:
                out.append(_UP[b % 26])
            elif ch in _LO:
                out.append(_LO[b % 26])
            elif ch in _DG:
                out.append(_DG[b % 10])
            else:
                out.append(ch)
        res = "".join(out)
        if res == original and len(original) > 1:
            res = res[::-1] if res[::-1] != original else res
        return res

    # -- bulk replacement --------------------------------------------------
    def _compile(self) -> re.Pattern | None:
        if self._regex is None and self.entries:
            # originals are stored normalized; match case-insensitively with
            # flexible whitespace, longest first.
            alts = sorted(self.entries, key=len, reverse=True)
            parts = [r"\s+".join(re.escape(w) for w in a.split(" ")) for a in alts]
            self._regex = re.compile("|".join(parts), re.IGNORECASE)
        return self._regex

    def replace_text(self, text: str, same_length: bool = False) -> str:
        rx = self._compile()
        if rx is None:
            return text

        def sub(m: re.Match) -> str:
            orig = m.group(0)
            if same_length:
                return self.samelen(orig)
            return _case_like(orig, self.entries[norm(orig)][1])

        return rx.sub(sub, text)

    def replace_bytes(self, data: bytes) -> bytes:
        """Same-length replacement on raw bytes (ASCII and UTF-16LE)."""
        for key in sorted(self.entries, key=len, reverse=True):
            for enc in ("ascii", "utf-16-le"):
                try:
                    needle = key.encode(enc)
                except UnicodeEncodeError:
                    continue
                if len(needle) < 3:
                    continue
                rx = re.compile(
                    b"".join(re.escape(bytes([c])) if c != 0x20 else b"[ _]" for c in needle)
                    if enc == "ascii"
                    else re.escape(needle),
                    re.IGNORECASE,
                )

                def sub(m: re.Match, enc=enc) -> bytes:
                    raw = m.group(0)
                    text = raw.decode(enc, "replace")
                    rep = self.samelen(text).encode(enc, "replace")
                    return rep if len(rep) == len(raw) else raw

                data = rx.sub(sub, data)
        return data
