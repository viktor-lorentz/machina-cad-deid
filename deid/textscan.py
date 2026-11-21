"""Regex harvesters shared across formats (emails, domains, usernames in paths)."""

from __future__ import annotations

import re

EMAIL = re.compile(rb"[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9-]{1,63}(?:\.[A-Za-z0-9-]{1,63})*\.[A-Za-z]{2,24}")
URL_HOST = re.compile(rb"https?://([A-Za-z0-9-]{1,63}(?:\.[A-Za-z0-9-]{1,63})+)", re.I)
WWW_HOST = re.compile(rb"\bwww\.([A-Za-z0-9-]{1,63}(?:\.[A-Za-z0-9-]{1,63})+)", re.I)
# usernames inside absolute paths
WIN_USER = re.compile(rb"[A-Za-z]:[\\/]+(?:Users|Documents and Settings)[\\/]+([^\\/\x00\"'<>|:*?\r\n]{2,40})[\\/]", re.I)
NIX_USER = re.compile(rb"/(?:home|Users)/([A-Za-z0-9._-]{2,40})/")
DOMAIN_USER = re.compile(rb"\b([A-Z][A-Z0-9-]{1,15})\\\\?([A-Za-z][A-Za-z0-9._-]{1,30})\b")
PHONE = re.compile(rb"(?<![\d.])\+?\d{1,3}[ .-]?\(?\d{2,4}\)?[ .-]\d{3,4}[ .-]\d{3,4}(?![\d.])")

# Hosts that belong to standards bodies, vendors and infrastructure, not owners.
GENERIC_HOSTS = {
    "w3.org", "www.w3.org", "ns.adobe.com", "adobe.com", "purl.org", "openxmlformats.org",
    "schemas.openxmlformats.org", "schemas.microsoft.com", "microsoft.com", "inkscape.org",
    "www.inkscape.org", "sodipodi.sourceforge.net", "creativecommons.org", "github.com",
    "gitlab.com", "freecad.org", "www.freecad.org", "freecadweb.org", "www.freecadweb.org",
    "solidworks.com", "www.solidworks.com", "autodesk.com", "www.autodesk.com", "spatial.com",
    "www.spatial.com", "iso.org", "www.iso.org", "ptc.com", "www.ptc.com", "google.com",
    "youtube.com", "www.youtube.com", "wikipedia.org", "en.wikipedia.org", "example.com",
    "3mf.io", "schemas.microsoft.com", "opencascade.com", "www.opencascade.com",
    "dublincore.org", "xmlns.com", "apache.org", "www.apache.org", "mozilla.org",
    "python.org", "www.python.org", "ietf.org", "www.ietf.org", "openscad.org", "kicad.org",
    "www.kicad.org", "bambulab.com", "prusa3d.com", "ultimaker.com", "w3c.org",
}
GENERIC_USERS = {"public", "default", "all users", "administrator", "admin", "user", "users",
                 "shared", "guest", "runner", "root", "ubuntu", "build", "appdata"}


def _d(b: bytes) -> str:
    return b.decode("latin-1")


def scan(data: bytes) -> list[tuple[str, str]]:
    """Return (value, kind) identity candidates found by pattern."""
    out: list[tuple[str, str]] = []
    for m in EMAIL.finditer(data):
        out.append((_d(m.group(0)), "email"))
    for rx in (URL_HOST, WWW_HOST):
        for m in rx.finditer(data):
            h = _d(m.group(1)).lower().rstrip(".")
            base = ".".join(h.split(".")[-2:])
            if h not in GENERIC_HOSTS and base not in GENERIC_HOSTS:
                out.append((h, "domain"))
    for rx in (WIN_USER, NIX_USER):
        for m in rx.finditer(data):
            u = _d(m.group(1)).strip()
            if u.lower() not in GENERIC_USERS:
                out.append((u, "account"))
    return out
