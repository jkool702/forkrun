#!/bin/bash
# Rented-EPYC day runner (documented, NOT yet executed — owner's call after
# single-socket debug). Portable one-command suite for a fresh 2-socket
# Ubuntu/Fedora rental with sudo:
#   bash run_rental.sh [OUTPUT_DIR]
# Installs deps, runs the full single-socket-equivalent suite, and writes a
# SEPARATELY-LABELED table (never merged with the lab table). One command,
# one output directory, no interactive steps. Copy the output dir off after.
set -u
OUT="${1:-$HOME/stage0-rental}"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
mkdir -p "$OUT"
echo "[rental] installing deps (needs sudo) ..."
if command -v apt-get >/dev/null 2>&1; then
    sudo apt-get update -qq
    sudo apt-get install -y -qq python3 python3-numpy gcc make parallel time git >/dev/null
elif command -v dnf >/dev/null 2>&1; then
    sudo dnf install -y -q python3 python3-numpy gcc make parallel time git >/dev/null
else
    echo "[rental] FATAL: no apt-get/dnf" >&2; exit 1
fi
echo "[rental] hardware:"; grep -m1 "model name" /proc/cpuinfo; free -g | head -n 2
echo "[rental] running suite into $OUT ..."
cd "$REPO_DIR/benchmarks/python"
python3 run_stage0.py
echo "[rental] relabeling table as rental hardware ..."
python3 - "$OUT" <<'EOF'
import csv, sys, glob, os
out = sys.argv[1]
os.makedirs(out, exist_ok=True)
for name in ("stage0_table_single_socket.csv", "rows.json", "crossover.csv",
             "stage0_table_single_socket.md", "stage0_fault_isolation.md",
             "stage0_report.md", "progress.log"):
    src = os.path.join("results", name)
    if os.path.exists(src):
        import shutil
        shutil.copy(src, os.path.join(out, "RENTAL_" + name))
print("rental outputs ->", out)
print("NOTE: RENTAL_ tables carry the rental hardware label from collection;")
print("never merge them with the single-socket lab table.")
EOF
