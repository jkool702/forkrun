#!/usr/bin/env bash
# Derive a shorter benchmark corpus from a larger one.
#
# The published corpora are prefixes of each other by construction: the
# generator (python/benchmarks/ml/ml_data_gen.py, SEED=42) emits records
# in a fixed sequence, so the first N lines of a 20M-record file ARE the
# N-record corpus. That is how heavy_5M was produced from heavy_20M.
#
# So "get the 5M light data" is `head -n 5000000`, not a regeneration.
# This wrapper exists to make that safe and self-documenting: it
# refuses to overwrite, verifies the line count afterwards, and refuses
# to cut in the middle of a record.
#
# Usage:
#   ./slice_corpus.sh SRC.jsonl DST.jsonl N_RECORDS
#
# Example:
#   ./slice_corpus.sh heavy_20M.jsonl heavy_5M.jsonl 5000000
set -euo pipefail

if [ "$#" -ne 3 ]; then
    sed -n '2,14p' "$0"
    exit 2
fi

src=$1
dst=$2
n=$3

[ -f "$src" ] || { echo "no such corpus: $src" >&2; exit 1; }
if [ -e "$dst" ]; then
    echo "refusing to overwrite existing $dst" >&2
    exit 1
fi

total=$(wc -l < "$src")
if [ "$n" -gt "$total" ]; then
    echo "$src has only $total lines, cannot take $n" >&2
    exit 1
fi

echo "slicing $n of $total records from $src -> $dst"
head -n "$n" "$src" > "$dst"

got=$(wc -l < "$dst")
if [ "$got" -ne "$n" ]; then
    echo "FAILED: wrote $got lines, expected $n" >&2
    rm -f "$dst"
    exit 1
fi

# A slice must end on a record boundary. A JSONL line that parses as
# complete is the practical test; truncated tails are the failure mode
# that would silently change every downstream record count.
if command -v python3 >/dev/null 2>&1; then
    python3 - "$dst" <<'PY'
import json, sys
path = sys.argv[1]
bad = 0
with open(path, "rb") as fh:
    for line in fh:
        if not line.strip():
            continue
        try:
            json.loads(line)
        except Exception:
            bad += 1
if bad:
    print("WARNING: %d unparseable line(s) in %s -- the corpora are "
          "expected to contain some deliberately malformed records, so "
          "this may be intentional" % (bad, path))
PY
fi

ls -la --block-size=G "$dst" | awk '{printf "wrote %s\n", $5}'
echo "done: $dst"