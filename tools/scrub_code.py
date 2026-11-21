"""Package hygiene for attempt-N/code/: drop working notes/test fixtures (they quote corpus strings)
and pass every remaining text file through the content registry, so code/ carries no original identifiers."""
import os
import shutil
import sys

from deid.rewrite import load_mappers

root, reg = sys.argv[1], sys.argv[2]
for d in ("docs", "tests", "tools", "infra"):
    shutil.rmtree(os.path.join(root, d), ignore_errors=True)
for f in ("IDEAS.md", "results.tsv"):
    try:
        os.remove(os.path.join(root, f))
    except FileNotFoundError:
        pass
secret = os.environ.get("DEID_SECRET", "machina-deid-default-secret").encode()
allm, content = load_mappers(reg, secret)
n = 0
for dp, _, fn in os.walk(root):
    for f in fn:
        if not f.endswith((".py", ".md", ".txt", ".toml", ".lock", ".sh", ".cfg")):
            continue
        p = os.path.join(dp, f)
        t = open(p, encoding="utf-8").read()
        u = content.replace_text(t)
        if u != t:
            open(p, "w", encoding="utf-8").write(u)
            n += 1
print(f"scrub_code: {n} files rewritten")
