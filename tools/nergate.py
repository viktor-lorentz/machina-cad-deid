"""Gate NER-sourced registry entries (agent C). usage: nergate.py IN_REG OUT_REG DROPPED.tsv
Drops NER entries made only of common lowercase dictionary words (generic phrases, engineering terms)."""
import json, re, sys, collections

LOWER = set()
for w in open("/usr/share/dict/words", encoding="utf-8", errors="ignore"):
    w = w.strip()
    if w and w.islower() and w.isalpha():
        LOWER.add(w)
LOWER |= {"thru", "qty", "assy", "pcb", "cad", "cnc", "led", "usb", "rev", "dwg", "pdf", "stp", "zip", "etc"}
TOK = re.compile(r"[A-Za-zÀ-ÿ]+")


def toks(v):
    return [t for t in TOK.findall(v) if len(t) >= 2]


def generic(v):
    t = toks(v)
    # mixed-case tokens (IndIGO, McMaster) are names, not dictionary words
    return bool(t) and all(x.lower() in LOWER and (x.islower() or x.istitle() or x.isupper()) for x in t)


def drop(kind, v):
    t = toks(v)
    if kind in ("phone", "email", "domain", "account", "part"):
        return None
    if not t:
        return "no-letters" if kind != "address" else None
    if v == v.lower() and generic(v):
        return "lowercase-generic"
    if kind == "address":
        if not re.search(r"\d", v) and sum(1 for x in t if x[0].isupper() and x.lower() not in LOWER) < 1:
            return "address-no-proper"
        if re.search(r"(?i)\b(address|zip code|thru)\b", v):
            return "address-template"
    if kind in ("company", "project") and generic(v) and not re.search(r"\d", v):
        return "dict-words-" + kind
    return None


def main():
    r = json.load(open(sys.argv[1]))
    keep, why = [], collections.Counter()
    with open(sys.argv[3], "w") as o:
        for i in r["identities"]:
            if i.get("source") == "ner-sel.tsv":
                d = drop(i["kind"], i["value"])
                if d:
                    why[d] += 1
                    o.write("%s\t%s\t%s\n" % (d, i["kind"], i["value"]))
                    continue
            keep.append(i)
    r["identities"] = keep
    json.dump(r, open(sys.argv[2], "w"))
    print("dropped", sum(why.values()), why.most_common())


if __name__ == "__main__":
    main()
