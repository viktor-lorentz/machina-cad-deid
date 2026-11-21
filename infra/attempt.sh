#!/bin/bash
# Build one attempt on the VM: rewrite -> leakscan -> local check -> package.
# Usage (inside tmux): bash infra/attempt.sh N [rewrite flags...]
# Output: /data/attempts/attempt-N/{corpus,code,README.txt} + logs in /data/attempts/attempt-N.*.log
set -euo pipefail
N="$1"; shift
FLAGS="$*"
CODE=/data/code
OUT=/data/attempts/attempt-$N
REG=${REG:-/data/registry/registry.json}
PY=$CODE/.venv/bin/python
export PYTHONUNBUFFERED=1
cd "$CODE"
echo "== disk before"; df -h /data | tail -1
AVAIL=$(df --output=avail -B1G /data | tail -1 | tr -d ' ')
if [ "$AVAIL" -lt 200 ]; then echo "ABORT: only ${AVAIL}G free"; exit 1; fi
rm -rf "$OUT"; mkdir -p "$OUT"
T0=$(date +%s)
$PY -m deid.cli rewrite /data/input "$OUT/corpus" --registry "$REG" $FLAGS
T1=$(date +%s); echo "== rewrite took $((T1-T0))s"
mv "$OUT/rewrite-results.json" "/data/attempts/attempt-$N.results.json"
$PY -m deid.cli leakscan "$OUT/corpus" --registry "$REG" > /dev/null 2> "/data/attempts/attempt-$N.leak.log" || true
tail -3 "/data/attempts/attempt-$N.leak.log"
$PY -m deid.cli check /data/input "$OUT/corpus" --results "/data/attempts/attempt-$N.results.json" --registry "$REG" 2>&1 | tee "/data/attempts/attempt-$N.check.log" | head -1
T2=$(date +%s); echo "== scans took $((T2-T1))s"
# code/: exact source at this commit + pinned dependency versions
mkdir -p "$OUT/code"
git archive HEAD | tar -x -C "$OUT/code"
$CODE/.venv/bin/pip freeze > "$OUT/code/requirements.lock"
git rev-parse HEAD > "$OUT/code/COMMIT"
$PY -m deid.cli readme --attempt "attempt-$N" --results "/data/attempts/attempt-$N.results.json" \
  --registry "$REG" --flags "$FLAGS" -o "$OUT/README.txt"
echo "== objects: $(find "$OUT/corpus" -type f | wc -l)  size: $(du -sh "$OUT/corpus" | cut -f1)"
echo "== disk after"; df -h /data | tail -1
echo "ATTEMPT $N READY ($(git rev-parse --short HEAD))"
