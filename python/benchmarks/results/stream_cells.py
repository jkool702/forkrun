"""One cell per process: file vs streamed pipe, a single (payload,
config, output) combination.

Isolating each cell in its own process is deliberate. An earlier
all-in-one harness returned 0 records for an arm whose isolated run was
correct, and 16 back-to-back map() calls in one process are all fine --
so the fault is in the harness's own cross-arm state, not in forkrun.
A fresh process per cell has nowhere to carry that, which makes the
numbers trustworthy enough to publish.

Usage: cell.py <variant> <payload> <config> <output> <file|pipe> [nodes]

`nodes` defaults to "auto" -- the DEFAULT configuration. This box boots
numa=fake=4, so that resolves to 4 nodes. An earlier version of this
study hardcoded nodes=1 (UMA) and therefore characterised a path users
do not get by default; on this box the two differ by ~50-100% on a
streamed pipe.
"""
import os
import statistics
import sys
import time

sys.path.insert(0, '/mnt/ramdisk/forkrun/python')
sys.path.insert(0, '/mnt/ramdisk/forkrun/python/benchmarks/ml')
import forkrun
from bench_ml_pipeline import FORKRUN_PAYLOADS, count_results

CORPORA = {
    'light':  ('/mnt/ramdisk/numa1/ml/light_5M.jsonl', 5000000),
    'medium': ('/mnt/ramdisk/numa1/ml/medium_5M.jsonl', 4997892),
    'heavy':  ('/tmp/opencode/heavy_5M.jsonl', 4997982),
}
WORK = '/tmp/opencode/mlbench'
TRIALS = 3


def main():
    variant, payload_kind, cfg, output, source = sys.argv[1:6]
    nodes = sys.argv[6] if len(sys.argv) > 6 else "auto"
    path, expect = CORPORA[variant]
    orch = (cfg == "default")
    order = "index" if orch else "none"

    if payload_kind == "plugin":
        payload = "%s/ml_plugin_%s.so:ml_process_%s" % (WORK, variant,
                                                        variant)
        mode = "plugin"
    else:
        payload = FORKRUN_PAYLOADS[variant]
        mode = "python"

    n_bytes = os.path.getsize(path)

    def run_file():
        return forkrun.map(payload, path, mode=mode, workers=28, nodes=nodes,
                           orchestrator=orch, order=order, output=output)

    def run_pipe():
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
            except BaseException:
                rc = 1
            finally:
                os._exit(rc)
        os.close(w)
        try:
            return forkrun.map(payload, r, mode=mode, workers=28, nodes=nodes,
                               orchestrator=orch, order=order, output=output)
        finally:
            os.close(r)
            _, st = os.waitpid(pid, 0)
            if st != 0:
                raise RuntimeError("pipe writer failed: status %d" % st)

    make = run_file if source == "file" else run_pipe

    make()                                    # warmup
    times, n_out = [], None
    for _ in range(TRIALS):
        t0 = time.perf_counter()
        out = make()
        times.append(time.perf_counter() - t0)
        n_out = count_results(out)
        del out

    if n_out != expect:
        raise SystemExit("EXACTNESS FAILURE %s/%s/%s/%s/%s: %d != %d"
                         % (variant, payload_kind, cfg, output, source,
                            n_out, expect))
    med = statistics.median(times)
    print("RESULT %s %s %s %s %s %s %.4f %.4f %d"
          % (variant, payload_kind, cfg, output, source, nodes, med,
             n_bytes / 1e6 / med, n_out), flush=True)


if __name__ == "__main__":
    main()