"""Command line entry point: `python -m deid.cli <command> ...`."""

from __future__ import annotations

import argparse


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="deid")
    sub = ap.add_subparsers(dest="cmd", required=True)

    h = sub.add_parser("harvest", help="collect identity candidates from the input corpus")
    h.add_argument("input")
    h.add_argument("-o", "--out", default="registry/candidates.json")
    h.add_argument("-j", "--workers", type=int, default=None)

    a = ap.parse_args(argv)
    if a.cmd == "harvest":
        from deid import harvest

        harvest.run(a.input, a.out, a.workers)


if __name__ == "__main__":
    main()
