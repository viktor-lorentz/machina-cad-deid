"""Command line entry point: `python -m deid.cli <command> ...`."""

from __future__ import annotations

import argparse
import os


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="deid")
    sub = ap.add_subparsers(dest="cmd", required=True)

    h = sub.add_parser("harvest", help="collect identity candidates from the input corpus")
    h.add_argument("input")
    h.add_argument("-o", "--out", default="registry/candidates.json")
    h.add_argument("-j", "--workers", type=int, default=None)

    b = sub.add_parser("build-registry", help="filter candidates into the identity registry")
    b.add_argument("candidates")
    b.add_argument("-o", "--out", default="registry/registry.json")

    r = sub.add_parser("rewrite", help="write the de-identified corpus")
    r.add_argument("input")
    r.add_argument("output")
    r.add_argument("--registry", default="registry/registry.json")
    r.add_argument("--rename", action="store_true", help="rename identifying path segments")
    r.add_argument("--archives", action="store_true", help="recurse into .zip archives")
    r.add_argument("-j", "--workers", type=int, default=None)

    lk = sub.add_parser("leakscan", help="count registry identities still present in output")
    lk.add_argument("output")
    lk.add_argument("--registry", default="registry/registry.json")
    lk.add_argument("-j", "--workers", type=int, default=None)

    c = sub.add_parser("check", help="local checker on held-out repos")
    c.add_argument("input")
    c.add_argument("output")
    c.add_argument("--results", required=True, help="rewrite-results.json")
    c.add_argument("--registry", default="registry/registry.json")
    c.add_argument("-n", type=int, default=3000)
    c.add_argument("-j", "--workers", type=int, default=None)

    rd = sub.add_parser("readme", help="write README.txt for an attempt")
    rd.add_argument("--attempt", required=True)
    rd.add_argument("--results", required=True)
    rd.add_argument("--registry", default="registry/registry.json")
    rd.add_argument("--flags", default="")
    rd.add_argument("-o", "--out", required=True)

    a = ap.parse_args(argv)
    if a.cmd == "readme":
        import platform

        from deid import readme

        readme.write(a.attempt, a.results, a.registry, a.out, a.flags, platform.python_version())
        return
    secret = os.environ.get("DEID_SECRET", "machina-deid-default-secret").encode()
    if a.cmd == "harvest":
        from deid import harvest

        harvest.run(a.input, a.out, a.workers)
    elif a.cmd == "build-registry":
        from deid.registry import build

        build.build(a.candidates, a.out)
    elif a.cmd == "rewrite":
        from deid import rewrite

        rewrite.run(a.input, a.output, a.registry, secret,
                    {"rename": a.rename, "archives": a.archives}, a.workers)
    elif a.cmd == "leakscan":
        from deid import leakscan

        leakscan.run(a.output, a.registry, secret, a.workers)
    elif a.cmd == "check":
        from deid import checker

        checker.run(a.input, a.output, a.results, a.registry, secret, a.n, a.workers)


if __name__ == "__main__":
    main()
