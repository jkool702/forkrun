#!/bin/bash
# Stage 0 one-command entry point. Run from anywhere:
#   bash benchmarks/python/run_stage0.sh [subset]
# subset: jsonl,transform,tensor,streaming,faults (comma list; default all).
# Results always land in benchmarks/python/results/ (committed tables) with
# scratch in inputs/, work/, logs/ (gitignored). Long legs run as
# subprocesses with generous timeouts; for machines where an interactive
# shell may time out, launch with nohup and poll results/progress.log.
set -u
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SUBSET="${1:-all}"
cd "$REPO/benchmarks/python"
exec python3 run_stage0.py "$SUBSET"
