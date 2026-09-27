"""§7 leg 5: heavy-20M EPYC-preview trio (W-NUMA2 gate re-run).

@4 x4, auto x4, nodes=1 x2 — sequential in-process maps
(ml_plugin_heavy, workers=28, order=index), each byte-exact vs
the nodes=1 reference, zero drain-audit warnings, DIAG_NUMA1
telemetry recorded. Results to stdout (captured to file).

Setup (once per machine):
  gcc -O3 -shared -fPIC -march=native -I ring_loadables \\
      -o /tmp/ml_heavy.so python/benchmarks/ml/plugins/ml_plugin_heavy.c -lm
  python3 -c "import sys; sys.path.insert(0, 'python/benchmarks/ml');
from ml_data_gen import generate_data
generate_data('/tmp/heavy20m.jsonl', 20000000, variant='heavy',
malformed_pct=0.0)"   # ~26.9GB; generate in parallel chunks if slow

  python3 dev/tools/numa_quads.py > /tmp/rel_leg5_quads.log 2>&1

Inputs overridable via env (defaults = v3.6.0 gate):
  FORKRUN_QUADS_INPUT (default /tmp/heavy20m.jsonl)
  FORKRUN_QUADS_PLUGIN (default /tmp/ml_heavy.so:ml_process_heavy)
On real multi-socket NUMA, nodes="auto" follows the boot topology
and "@4" still forces 4 logical nodes; both are exercised as-is.
Exit 0 + ALL-EXACT means the gate passes.
"""
import gc
import os
import sys
import time

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))), "python"))
os.environ["FORKRUN_DIAG_NUMA1"] = "1"

import forkrun  # noqa: E402

PATH = os.environ.get("FORKRUN_QUADS_INPUT", "/tmp/heavy20m.jsonl")
SPEC = os.environ.get("FORKRUN_QUADS_PLUGIN",
                      "/tmp/ml_heavy.so:ml_process_heavy")


def run_once(nodes, tag, fd2_path):
    saved = os.dup(2)
    cap = os.open(fd2_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
    os.dup2(cap, 2)
    os.close(cap)
    t0 = time.monotonic()
    try:
        out = forkrun.map(SPEC, PATH, mode="plugin", workers=28,
                          order="index", nodes=nodes)
    finally:
        os.dup2(saved, 2)
        os.close(saved)
    dt = time.monotonic() - t0
    with open(fd2_path, "rb") as fh:
        err = fh.read()
    return out, dt, err


def main():
    plan = [("1", 2), ("@4", 4), ("auto", 4)]
    ref = None
    all_ok = True
    for nodes, count in plan:
        for i in range(count):
            tag = "%s#%d" % (nodes, i + 1)
            err_path = "/tmp/numa_quad_%s.err" % tag.replace("@", "at")
            out, dt, err = run_once(nodes, tag, err_path)
            blob = b"".join(out)
            nlines = blob.count(b"\n")
            del out
            gc.collect()
            if ref is None:
                ref = (len(blob), nlines,
                       __import__("hashlib").sha256(blob).hexdigest())
                # 27GB reference: hash+len+lines (SHA-256 over ordered
                # bytes; the F-NUMA1 failure mode — whole-suffix loss
                # — moves all three).
                status = "REF len=%d lines=%d sha=%s.. dt=%.1fs" % (
                    len(blob), nlines, ref[2][:16], dt)
                del blob
                gc.collect()
            else:
                h = __import__("hashlib").sha256(blob).hexdigest()
                ok = (len(blob), nlines, h) == ref
                status = "%s len=%d lines=%d sha=%s.. dt=%.1fs" % (
                    "EXACT" if ok else "MISMATCH", len(blob), nlines,
                    h[:16], dt)
                if not ok:
                    all_ok = False
                    status += " (ref len=%d lines=%d sha=%s..)" % (
                        ref[0], ref[1], ref[2][:16])
                del blob
                gc.collect()
            warn = b"NUMA partial completion" in err
            diag = b"DIAG-NUMA1" in err
            if warn:
                all_ok = False
            print("%s %s warn=%s diag=%s" % (tag, status, warn, diag),
                  flush=True)
    print("ALL-EXACT" if all_ok else "MISMATCHES-FOUND", flush=True)
    return 0 if all_ok else 1


sys.exit(main())
