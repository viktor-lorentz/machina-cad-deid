#!/bin/bash
# Upload a built attempt to the team's Builders folder and time it.
# Usage (inside tmux on the VM): bash infra/upload.sh <built-dir-name> <attempt-number>
#   e.g. bash infra/upload.sh 1b 1   -> uploads /data/attempts/attempt-1b as attempt-1/
# The 1-hour token is read from /data/secrets/token (never committed). When it
# expires mid-upload, upload.py waits for a new token written to the same file.
set -euo pipefail
SRC=/data/attempts/attempt-$1
N=$2
TEAM=cf6d6745-d9bc-40bd-86b1-ac9c2110a6ea
DEST="gs://builders-machina-submissions-1120/teams/$TEAM/attempt-$N/"
export MACHINA_UPLOAD_TOKEN="$(cat /data/secrets/token)"
T0=$(date +%s)
python3 /data/upload.py --dest "$DEST" --corpus "$SRC/corpus" --code "$SRC/code" --readme "$SRC/README.txt" \
  --token-file /data/secrets/token
T1=$(date +%s)
echo "UPLOAD DONE attempt-$N from $SRC in $((T1-T0))s -> $DEST"
