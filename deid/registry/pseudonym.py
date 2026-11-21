"""Deterministic same-length pseudonyms and a fast global replacer.

Design
------
Every identity maps to ONE pseudonym with exactly the same length and layout
as the original: letters stay letters (pronounceable syllables), digits stay
digits, separators stay where they are. The case of each occurrence is
re-applied per character. Consequences:

* the same identity reads the same everywhere (text, binary, paths);
* byte offsets never shift, so length-prefixed strings (SAT), Hollerith
  fields (IGES), fixed-size OLE streams and binary headers stay valid;
* pseudonyms are name-like, never blanks or redaction marks.

Matching is ASCII-case-insensitive with alphanumeric word boundaries, done
with an Aho-Corasick automaton over bytes (ASCII and UTF-16LE).
"""

from __future__ import annotations

import hashlib
import hmac
import re
from dataclasses import dataclass, field

import ahocorasick

_CONS = "bdfgklmnprstvz"
_VOW = "aeiou"
_ALNUM = re.compile(r"[A-Za-z0-9]")
_KEEP_WORDS = {"of", "de", "da", "del", "di", "du", "la", "le", "von", "van", "der", "den", "the", "and", "y", "e"}


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip()).lower()


def _stream(secret: bytes, key: str, salt: int):
    block = hmac.new(secret, f"{key}|{salt}".encode(), hashlib.sha256).digest()
    while True:
        yield from block
        block = hashlib.sha256(block).digest()


def _base(secret: bytes, key: str, salt: int) -> str:
    """Lowercase pseudonym skeleton with the same layout as `key`."""
    rnd = _stream(secret, key, salt)
    out = []
    vowel_next = next(rnd) % 2 == 0
    for ch in key:
        if "a" <= ch <= "z":
            out.append(_VOW[next(rnd) % 5] if vowel_next else _CONS[next(rnd) % len(_CONS)])
            vowel_next = not vowel_next
        elif "0" <= ch <= "9":
            out.append(str(next(rnd) % 10))
        else:
            out.append(ch)
            vowel_next = next(rnd) % 2 == 0
    return "".join(out)


def _random_base(secret: bytes, key: str, salt: int) -> str:
    """Wider space (any letter) for short keys whose syllable space is used up."""
    rnd = _stream(secret, key, salt)
    return "".join(chr(97 + next(rnd) % 26) if "a" <= c <= "z" else str(next(rnd) % 10) if "0" <= c <= "9" else c
                   for c in key)


def apply_case(occurrence: str, base: str) -> str:
    """Map base's alnum chars onto occurrence's alnum positions, keeping case."""
    alnum = [c for c in base if _ALNUM.match(c)]
    res, i = [], 0
    for ch in occurrence:
        if _ALNUM.match(ch) and i < len(alnum):
            c = alnum[i]
            i += 1
            res.append(c.upper() if ch.isupper() else c)
        else:
            res.append(ch)
    return "".join(res)


@dataclass
class Mapper:
    secret: bytes = b"machina-deid-default-secret"
    entries: dict[str, str] = field(default_factory=dict)  # norm(original) -> base pseudonym
    kinds: dict[str, str] = field(default_factory=dict)
    _taken: set[str] = field(default_factory=set)
    _auto: dict = field(default_factory=dict)
    _tok: dict = field(default_factory=dict)        # token -> pseudo token (injective)
    _tok_taken: set = field(default_factory=set)

    def _token(self, tok: str) -> str:
        """Pseudonym of one lowercase word; the same word maps to the same pseudo-word everywhere."""
        if tok in self._tok:
            return self._tok[tok]
        for salt in range(300):
            sec = self.secret + b"|tok"
            cand = _base(sec, tok, salt) if salt < 50 else _random_base(sec, tok, salt)
            if cand != tok and cand not in self._tok_taken:
                break
        else:
            cand = tok  # space exhausted (1-2 letter words): leave as is
        self._tok[tok] = cand
        self._tok_taken.add(cand)
        return cand

    def _compose(self, key: str, kind: str) -> str:
        """Word-by-word pseudonym: 'j. smith' and 'smith' share the surname pseudonym,
        'user@dept.uni.edu' reuses the pseudonyms of 'user' and 'uni'."""
        runs = list(re.finditer(r"[a-z0-9]+", key))
        last_label = runs[-1] if runs and kind in ("email", "domain") and "." in key else None
        out, pos = [], 0
        for r in runs:
            out.append(key[pos:r.start()])
            t = r.group(0)
            keep = (len(t) == 1 and not t.isdigit()) or t in _KEEP_WORDS or r is last_label
            out.append(t if keep else self._token(t))
            pos = r.end()
        out.append(key[pos:])
        return "".join(out)

    def add(self, original: str, kind: str = "name") -> str:
        key = norm(original)
        if len(_ALNUM.findall(key)) < 2:
            return key
        if key in self.entries:
            return self.entries[key]
        if kind != "phone":
            cand = self._compose(key, kind)
            if cand != key and cand not in self._taken and cand not in self.entries:
                self._taken.add(cand)
                self.entries[key] = cand
                self.kinds[key] = kind
                self._auto.clear()
                return cand
        salt = 0
        while True:
            cand = _base(self.secret, key, salt) if salt < 50 else _random_base(self.secret, key, salt)
            if cand != key and cand not in self._taken and cand not in self.entries:
                break
            salt += 1
            if salt > 500:  # pseudonym space exhausted (very short names): leave unmapped
                return key
        self._taken.add(cand)
        self.entries[key] = cand
        self.kinds[key] = kind
        self._auto.clear()
        return cand

    def pseudonym(self, occurrence: str) -> str:
        return apply_case(occurrence, self.entries[norm(occurrence)])

    # -- automaton ---------------------------------------------------------
    def _automaton(self, enc: str):
        if enc not in self._auto:
            A = ahocorasick.Automaton(ahocorasick.STORE_ANY, ahocorasick.KEY_STRING)
            n = 0
            codec = "utf-8" if enc == "ascii" else enc  # ASCII pass also matches UTF-8 accented names
            for key in self.entries:
                try:
                    kb = key.encode(codec)
                except UnicodeEncodeError:
                    continue
                A.add_word(kb.decode("latin-1"), (len(kb), key))
                n += 1
            if n:
                A.make_automaton()
            self._auto[enc] = A if n else None
        return self._auto[enc]

    def find(self, data: bytes, enc: str = "ascii") -> list[tuple[int, int, str]]:
        """Non-overlapping (start, end, key) matches, longest first."""
        A = self._automaton(enc)
        if A is None or not data:
            return []
        low = data.lower()
        unit = 2 if enc == "utf-16-le" else 1
        hits = []
        for end_idx, (ln, key) in A.iter(low.decode("latin-1")):
            start, end = end_idx - ln + 1, end_idx + 1
            if _is_word(data, start - unit, unit) or _is_word(data, end, unit):
                continue
            hits.append((start, end, key))
        hits.sort(key=lambda h: (h[0], -(h[1] - h[0])))
        out, last = [], -1
        for h in hits:
            if h[0] >= last:
                out.append(h)
                last = h[1]
        return out

    def replace_bytes(self, data: bytes, encodings=("ascii", "utf-16-le"), accept=None) -> bytes:
        """Same-length replacement of every registered identity."""
        if not self.entries:
            return data
        buf = None
        for enc in encodings:
            src = bytes(buf) if buf is not None else data
            hits = self.find(src, enc)
            if not hits:
                continue
            if buf is None:
                buf = bytearray(data)
            for s, e, key in hits:
                if accept is not None and not accept(src, s, e):
                    continue
                codec = "utf-8" if enc == "ascii" else enc
                try:
                    occ = src[s:e].decode(codec)
                    rep = self.pseudonym(occ).encode(codec)
                except (UnicodeError, KeyError):
                    continue
                if len(rep) == e - s:
                    buf[s:e] = rep
        return bytes(buf) if buf is not None else data

    def replace_text(self, text: str) -> str:
        b = text.encode("utf-8", "surrogateescape")
        return self.replace_bytes(b, ("ascii",)).decode("utf-8", "surrogateescape")


def _is_word(data: bytes, pos: int, unit: int) -> bool:
    if pos < 0 or pos + unit > len(data):
        return False
    c = data[pos]
    if unit == 2 and data[pos + 1] != 0:
        return False
    return (48 <= c <= 57) or (65 <= c <= 90) or (97 <= c <= 122)
