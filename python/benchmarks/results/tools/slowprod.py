"""Slow-producer harness for measuring the PRE-FLIGHT WINDOW.

Replicates cell.py's run_pipe() exactly -- forked writer process (not a
thread: forkrun forks 21 times, and forking from a multi-threaded parent
is a documented deadlock hazard), same orchestrator/order, same
count_results exactness check -- and adds a GAP sleep between 1 MB
chunks so the producer delivers slowly.

That gap is what should stretch the window between "scanner forked" and
"first worker forked". If the window is architecturally short it should
barely move; if the pre-flight gates startup on the producer, it tracks
GAP directly.

Usage: GAP=0.004 FORKRUN_SRC=... python3 slowprod.py <variant> <config>
"""
import os
import sys
import time

sys.path.insert(0, '/mnt/ramdisk/forkrun/python/benchmarks/ml')
sys.path.insert(0, os.environ.get(
    'FORKRUN_SRC', '/mnt/ramdisk/forkrun/python'))

import forkrun
from bench_ml_pipeline import count_results

WORK = '/tmp/opencode/mlbench'
CORPORA = {
    'light':  ('/mnt/ramdisk/numa1/ml/light_5M.jsonl', 5000000),
    'medium': ('/mnt/ramdisk/numa1/ml/medium_5M.jsonl', 4997892),
}
GAP = float(os.environ.get('GAP', '0.004'))
NODES = os.environ.get('NODES', 'auto')
WORKERS = int(os.environ.get('WORKERS', '28'))
TRIALS = int(os.environ.get('TRIALS', '3'))


def run_pipe(path, payload, orch, order, output):
    r, w = os.pipe()
    pid = os.fork()
    if pid == 0:
        rc = 0
        try:
            os.close(r)
            with open(path, 'rb') as src, os.fdopen(w, 'wb') as dst:
                while True:
                    b = src.read(1 << 20)
                    if not b:
                        break
                    dst.write(b)
                    if GAP:
                        dst.flush()
                        time.sleep(GAP)
        except BaseException:
            rc = 1
        finally:
            os._exit(rc)
    os.close(w)
    try:
        return forkrun.map(payload, r, mode="plugin", workers=WORKERS,
                           nodes=NODES, orchestrator=orch, order=order,
                           output=output)
    finally:
        os.close(r)
        _, st = os.waitpid(pid, 0)
        if st != 0:
            raise RuntimeError("pipe writer failed: status %d" % st)


def main():
    variant = sys.argv[1] if len(sys.argv) > 1 else 'light'
    cfg = sys.argv[2] if len(sys.argv) > 2 else 'default'
    path, expect = CORPORA[variant]
    if os.environ.get('CORPUS'):
        path = os.environ['CORPUS']
        expect = int(os.environ['EXPECT'])
    payload = "%s/ml_plugin_%s.so:ml_process_%s" % (WORK, variant, variant)
    orch = (cfg == "default")
    order = "index" if orch else "none"

    if not os.environ.get('NOWARM'):
        run_pipe(path, payload, orch, order, "bytes")      # warmup
    times, n_out = [], None
    for _ in range(TRIALS):
        t0 = time.perf_counter()
        out = run_pipe(path, payload, orch, order, "bytes")
        times.append(time.perf_counter() - t0)
        n_out = count_results(out)
        del out
    times.sort()
    print("SLOWPROD variant=%s cfg=%s gap=%.4f nodes=%s median=%.3fs "
          "min=%.3fs records=%d %s"
          % (variant, cfg, GAP, NODES, times[len(times) // 2], times[0],
             n_out, "OK" if n_out == expect else "EXACTNESS-FAIL"))


main()