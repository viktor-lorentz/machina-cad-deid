"""Merge reviewed candidate lists (kind<TAB>value, global scope) into a registry.
Used for agent B's vendor list and agent C's NER candidates after they pass the recall gate."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from deid.registry.build import FORMAT_WORDS


def merge(base: str, tsvs: list[str], out: str) -> None:
    reg = json.loads(Path(base).read_text())
    have = {r["value"].lower() for r in reg["identities"]}
    added = 0
    for t in tsvs:
        for line in Path(t).read_text(encoding="utf-8").splitlines():
            if "\t" not in line:
                continue
            kind, value = line.split("\t", 1)
            value = value.strip()
            if len(value) < 2 or value.lower() in have or value.lower() in FORMAT_WORDS:
                continue
            reg["identities"].append({"value": value, "kind": kind.strip(), "scope": "global", "files": 1,
                                      "source": Path(t).name})
            have.add(value.lower())
            added += 1
    Path(out).write_text(json.dumps(reg, indent=1))
    print(f"merge: +{added} identities -> {out} ({len(reg['identities'])} total)")


if __name__ == "__main__":
    merge(sys.argv[1], sys.argv[3:], sys.argv[2])
