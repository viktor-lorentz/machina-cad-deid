import os

from deid import rewrite
from deid.rewrite import G, _UserPathMapper, rewrite_bytes


class _Reg:
    secret = b"test-secret"
    entries: dict = {}


def _setup(monkeypatch, on=True):
    monkeypatch.setitem(G, "allm", _Reg())
    monkeypatch.setitem(G, "_upm", None)
    if on:
        monkeypatch.setenv("DEID_USERPATH_RAW", "1")
    else:
        monkeypatch.delenv("DEID_USERPATH_RAW", raising=False)


def _blob():
    a = b"C:\\Users\\egomezpitarch.FUNDACIOCIM\\Google Drive\\x.sldprt"
    u = "C:\\Users\\egomezpitarch.FUNDACIOCIM\\Google Drive\\y".encode("utf-16-le")
    return b"\x00\x01\x02" + a + b"\xff\xfe" + u + b"\x00tail", a, u


def test_replaces_ascii_and_utf16_same_length(monkeypatch):
    _setup(monkeypatch)
    data, a, u = _blob()
    out = rewrite_bytes("a/b/2M2.SLDASM", data, object())
    assert len(out) == len(data)
    assert b"egomezpitarch" not in out
    assert "egomezpitarch".encode("utf-16-le") not in out
    assert b"\\Google Drive\\x.sldprt" in out
    # same login -> same pseudonym in both encodings
    login = out[out.index(b"C:\\Users\\") + 9:].split(b"\\")[0]
    assert login.decode().encode("utf-16-le") in out


def test_gate_off_and_other_ext_untouched(monkeypatch):
    data, _, _ = _blob()
    _setup(monkeypatch, on=False)
    assert rewrite_bytes("a/2M2.SLDASM", data, object()) == data
    _setup(monkeypatch)
    assert rewrite_bytes("a/readme.bin", data, object()) == data


def test_system_logins_kept(monkeypatch):
    _setup(monkeypatch)
    d = b"\x00C:\\Users\\Public\\Documents\\x"
    assert rewrite_bytes("a.sldprt", d, object()) == d


def test_creo_numbered_prt(monkeypatch):
    _setup(monkeypatch)
    data, _, _ = _blob()
    assert b"egomezpitarch" not in rewrite_bytes("p.prt.7", data, object())
