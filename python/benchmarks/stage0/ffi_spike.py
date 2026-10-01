#!/usr/bin/env python3
"""Stage 2 ctypes spike — FFI boundary cost measurement (W-V352-COMPLETE).

Zero engine changes: pure-Python measurement (stdlib only, gcc at runtime)
against a purpose-built probe micro-library — NOT forkrun_ring. It measures
the per-call overhead of the boundary the future Python frontend will pay
(claim/ack shaped calls + the Batch.data memoryview cost), producing the
"FFI boundary" row for the Stage 0 table.

Legs (each: warmup, then best-of-R repeats of an N-call timing loop):
  1. null call floor — ctypes CDLL call, no args, int return.
  2. claim-shaped call — 8 scalar args (u64/u32 mix), the arity/shape of
     the future claim boundary (fr_state_t identity + coords).
  3. claim-ptr call — single struct-pointer arg (the out-param shape:
     engine fills fr_state_t through the pointer).
  4. memoryview over a MAP_SHARED window — the Batch.data equivalent
     (slice-view creation over a shared mapping at batch offsets).
  5. Python fixed cost — a Python-level call with 8 bound args (the
     per-batch budget the crossover curve grants).

Outputs:
  stdout: one JSON summary line (bench_common-style contract).
  python/benchmarks/stage0/results/ffi_spike.json: full numbers + provenance.
  Stage 0 table row: appended to results/rows.json + tables regenerated
  (use --no-table-row to skip the table update, e.g. for dry runs).
"""

from __future__ import annotations

import ctypes
import json
import mmap
import os
import statistics
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
RESULTS = os.path.join(HERE, "results")
WORK = os.path.join(HERE, "work")

PROBE_C = r"""
#include <stdint.h>

int probe_null(void) { return 42; }

/* Claim-shaped: 8 scalars in the u64/u32 mix of the claim boundary. */
uint64_t probe_claim_shaped(uint64_t a, uint64_t b, uint32_t c, uint32_t d,
                            uint32_t e, uint32_t f, uint64_t g, uint64_t h) {
    return a + b + c + d + e + f + g + h;
}

/* Out-param shape: engine fills the struct through the pointer. */
struct claim_args {
    uint64_t a, b;
    uint32_t c, d, e, f;
};

uint64_t probe_claim_ptr(const struct claim_args *p) {
    return p->a + p->b + p->c + p->d + p->e + p->f;
}
"""

N_CALLS = 200_000
N_VIEWS = 20_000
REPEATS = 7
WINDOW_LEN = 1 << 20  # 1 MiB batch window
MAP_LEN = 64 << 20    # 64 MiB shared mapping


def build_probe():
    os.makedirs(WORK, exist_ok=True)
    c_path = os.path.join(WORK, "ffi_probe.c")
    so_path = os.path.join(WORK, "ffi_probe.so")
    with open(c_path, "w") as fh:
        fh.write(PROBE_C)
    proc = subprocess.run(
        ["gcc", "-O2", "-shared", "-fPIC", c_path, "-o", so_path],
        capture_output=True, text=True, timeout=300)
    if proc.returncode != 0:
        raise RuntimeError("probe build failed:\n%s" % proc.stderr)
    gcc_v = subprocess.run(["gcc", "--version"], capture_output=True,
                           text=True, timeout=60).stdout.splitlines()[0]
    return so_path, gcc_v


def best_per_call(repeats, n_calls, fn):
    """Best-of-R total time, converted to seconds per call."""
    totals = []
    for _ in range(repeats):
        t0 = time.perf_counter_ns()
        fn(n_calls)
        totals.append(time.perf_counter_ns() - t0)
    return min(totals) / n_calls / 1e9


def main() -> int:
    update_table = "--no-table-row" not in sys.argv
    so_path, gcc_v = build_probe()
    lib = ctypes.CDLL(so_path)

    null = lib.probe_null
    null.restype = ctypes.c_int
    null.argtypes = []

    shaped = lib.probe_claim_shaped
    shaped.restype = ctypes.c_uint64
    shaped.argtypes = [ctypes.c_uint64, ctypes.c_uint64, ctypes.c_uint32,
                       ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32,
                       ctypes.c_uint64, ctypes.c_uint64]

    class ClaimArgs(ctypes.Structure):
        _fields_ = [("a", ctypes.c_uint64), ("b", ctypes.c_uint64),
                    ("c", ctypes.c_uint32), ("d", ctypes.c_uint32),
                    ("e", ctypes.c_uint32), ("f", ctypes.c_uint32)]

    ptr = lib.probe_claim_ptr
    ptr.restype = ctypes.c_uint64
    ptr.argtypes = [ctypes.POINTER(ClaimArgs)]
    arg = ClaimArgs(1, 2, 3, 4, 5, 6)

    # Warmup (page in the .so, settle the CPU).
    for _ in range(10_000):
        null()
    assert null() == 42
    assert shaped(1, 2, 3, 4, 5, 6, 7, 8) == 36
    assert ptr(ctypes.byref(arg)) == 21

    null_s = best_per_call(REPEATS, N_CALLS, lambda n: [null() for _ in range(n)])
    shaped_s = best_per_call(REPEATS, N_CALLS,
                             lambda n: [shaped(1, 2, 3, 4, 5, 6, 7, 8)
                                        for _ in range(n)])
    ptr_s = best_per_call(REPEATS, N_CALLS,
                          lambda n: [ptr(ctypes.byref(arg)) for _ in range(n)])

    # Batch.data equivalent: MAP_SHARED window, slice-view per batch offset.
    mm = mmap.mmap(-1, MAP_LEN, prot=mmap.PROT_READ | mmap.PROT_WRITE,
                   flags=mmap.MAP_SHARED)
    mm[:] = b"\xab" * MAP_LEN
    base = memoryview(mm)
    stride = (MAP_LEN - WINDOW_LEN) // N_VIEWS

    def views(n):
        for k in range(n):
            off = (k * stride) % (MAP_LEN - WINDOW_LEN)
            v = base[off:off + WINDOW_LEN]
            v[0]  # touch: fault the view creation, not just the slice object

    for _ in range(1_000):
        v = base[0:WINDOW_LEN]
        v[0]
    del v
    view_s = best_per_call(REPEATS, N_VIEWS, views)
    del base
    mm.close()

    # Python-level fixed cost: call + 8-arg binding.
    def py_sink(a, b, c, d, e, f, g, h):
        return a

    for _ in range(10_000):
        py_sink(1, 2, 3, 4, 5, 6, 7, 8)
    py_s = best_per_call(REPEATS, N_CALLS,
                         lambda n: [py_sink(1, 2, 3, 4, 5, 6, 7, 8)
                                    for _ in range(n)])

    summary = {
        "null_call_us": round(null_s * 1e6, 3),
        "claim_shaped_us": round(shaped_s * 1e6, 3),
        "claim_ptr_us": round(ptr_s * 1e6, 3),
        "memoryview_window_us": round(view_s * 1e6, 3),
        "python_fixed_us": round(py_s * 1e6, 3),
        "n_calls": N_CALLS,
        "n_views": N_VIEWS,
        "repeats": REPEATS,
        "window_bytes": WINDOW_LEN,
        "map_bytes": MAP_LEN,
        "gcc": gcc_v,
        "python": sys.version.split()[0],
    }
    print(json.dumps(summary), flush=True)

    os.makedirs(RESULTS, exist_ok=True)
    sys.path.insert(0, HERE)
    from run_stage0 import hardware_label  # noqa: E402
    hw = hardware_label()
    full = dict(summary)
    full["hardware"] = hw
    full["probe"] = "python/benchmarks/stage0/work/ffi_probe.so (regenerable scratch)"
    with open(os.path.join(RESULTS, "ffi_spike.json"), "w") as fh:
        json.dump(full, fh, indent=1)
        fh.write("\n")

    if update_table:
        append_table_row(hw, summary)
    return 0


def append_table_row(hw, summary):
    """Append the FFI-boundary row to rows.json and regenerate the tables."""
    import report  # noqa: E402
    rows_path = os.path.join(RESULTS, "rows.json")
    with open(rows_path) as fh:
        data = json.load(fh)
    # Idempotent: replace any prior ffi-boundary row from this script.
    data["rows"] = [r for r in data["rows"] if r.get("niche") != "ffi-boundary"]
    notes = (
        "FFI boundary cost per claim: %.3f us (claim-ptr %.3f us) — "
        "measured against the ctypes null-call floor %.3f us; "
        "memoryview 1MiB window %.3f us; Python 8-arg fixed cost %.3f us. "
        "Context: the crossover data shows dispatch cost stops mattering "
        "above ~100us/record; the frontend per-batch budget is ~10-100ms "
        "(1000-line batches). Full numbers: results/ffi_spike.json. "
        "Zero engine involvement (probe micro-library, not forkrun_ring)."
        % (summary["claim_shaped_us"], summary["claim_ptr_us"],
           summary["null_call_us"], summary["memoryview_window_us"],
           summary["python_fixed_us"]))
    data["rows"].append({
        "niche": "ffi-boundary",
        "incumbent": "ctypes-null-floor",
        "incumbent_result_s": 0.0,
        "incumbent_rss_mb": 0.0,
        "forkrun_result_s": 0.0,
        "forkrun_rss_mb": 0.0,
        "ratio": "",
        "fault_outcome": "",
        "hardware": hw,
        "notes": notes,
    })
    with open(rows_path, "w") as fh:
        # No trailing newline: matches the committed rows.json byte style
        # (keeps the diff to the appended row only).
        fh.write(json.dumps(data, indent=1))
    ctx = {"rows": data["rows"], "faults": data.get("faults", []), "hw": hw}
    report.write_tables(ctx, RESULTS)
    print("appended ffi-boundary row; tables regenerated", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
