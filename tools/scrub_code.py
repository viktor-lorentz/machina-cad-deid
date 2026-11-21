"""Package hygiene for attempt-N/code/: drop working notes/test fixtures (they quote corpus strings)
Source files stay byte-exact so code/ reproduces corpus/."""
import os
import shutil
import sys

root, reg = sys.argv[1], sys.argv[2]
for d in ("docs", "tests", "tools", "infra"):
    shutil.rmtree(os.path.join(root, d), ignore_errors=True)
for f in ("IDEAS.md", "results.tsv"):
    try:
        os.remove(os.path.join(root, f))
    except FileNotFoundError:
        pass
print("code/: notes, tests and tools removed; source kept byte-exact for repeatability")
