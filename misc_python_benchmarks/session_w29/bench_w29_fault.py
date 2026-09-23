"""W-PY29 fault-injection throughput: recovery tax under worker death.

Medium 5M records, lines=100 (50k batches), order=index, orchestrator.
Core dumps disabled via RLIMIT_CORE=0 (inherited across fork):
  systemd-coredump spends ~10s per SEGV on multi-GB memfd mappings;
  that is environmental, not forkrun — this measures FORKRUN's cost.
Modes (per-idx markers, reset per pass — retries never re-fire):
  clean      : no kills (baseline)
  burst      : first W batches SIGKILLed (W deaths, front-loaded)
  sustained  : every Kth batch SIGKILLed (~W/2 deaths spread over run)
  segv-once  : single SIGSEGV at batch idx 5
  poison     : batch POISON_IDX raises on EVERY attempt -> killed 3
               times -> poison-skipped (no deaths; pipeline completes
               without exactly that batch)
Reports median s, rec/s, deaths fired, and byte-equality with clean
(poison: equality minus the poisoned batch).
"""
import glob
import os
import resource
import statistics
import sys
import tempfile
import time

HERE = "/mnt/ramdisk/forkrun/python/benchmarks"
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))

import forkrun  # noqa: E402

LINES = 100
BASE_RECORDS = 5_000_000  # kill schedule calibrated at this scale
RECORDS = int(sys.argv[1]) if len(sys.argv) > 1 else BASE_RECORDS
N_BATCHES = RECORDS // LINES
WORKERS = [8, 14, 28]
TRIALS = 2

# No core dumps in workers (fork-inherited): isolates forkrun's
# recovery cost from systemd-coredump's multi-GB dump time.
resource.setrlimit(resource.RLIMIT_CORE, (0, 0))

MOD_TMPL = """import os, signal
MARKER_DIR = {marker_dir!r}
MODE = {mode!r}
EVERY = {every!r}
BURST_N = {burst_n!r}
POISON_IDX = {poison_idx!r}
TAIL_N = {tail_n!r}
TAIL_SEGV_IDX = {tail_segv_idx!r}
N_BATCHES = {n_batches!r}
def payload(batch):
    from ml_payload import forkrun_payload_medium
    idx = batch.batch_index
    if MODE == 'poison':
        if idx == POISON_IDX:
            raise RuntimeError('deterministic poison batch %d' % idx)
    elif MODE == 'segv-once':
        if idx == 5:
            mark = os.path.join(MARKER_DIR, 'segv')
            if not os.path.exists(mark):
                open(mark, 'w').write('x')
                import ctypes
                ctypes.string_at(0)
    elif MODE == 'segv-tail':
        if idx == TAIL_SEGV_IDX:
            mark = os.path.join(MARKER_DIR, 'segv')
            if not os.path.exists(mark):
                open(mark, 'w').write('x')
                import ctypes
                ctypes.string_at(0)
    elif MODE == 'burst':
        if idx < BURST_N:
            mark = os.path.join(MARKER_DIR, 'idx-%d' % idx)
            if not os.path.exists(mark):
                open(mark, 'w').write('x')
                os.kill(os.getpid(), signal.SIGKILL)
    elif MODE == 'burst-tail':
        if idx >= N_BATCHES - BURST_N:
            mark = os.path.join(MARKER_DIR, 'idx-%d' % idx)
            if not os.path.exists(mark):
                open(mark, 'w').write('x')
                os.kill(os.getpid(), signal.SIGKILL)
    elif MODE == 'sustained':
        if idx % EVERY == 0:
            mark = os.path.join(MARKER_DIR, 'idx-%d' % idx)
            if not os.path.exists(mark):
                open(mark, 'w').write('x')
                os.kill(os.getpid(), signal.SIGKILL)
    return forkrun_payload_medium(batch)
"""


def reset_markers(d):
    for f in glob.glob(os.path.join(d, "*")):
        try:
            os.unlink(f)
        except OSError:
            pass


def count_markers(d):
    return len(glob.glob(os.path.join(d, "*")))


def run_pass(spec, path, workers):
    t0 = time.perf_counter()
    res = forkrun.map(spec, path, workers=workers, order="index",
                      lines=LINES, orchestrator=True)
    return time.perf_counter() - t0, res


def main():
    path = "/mnt/ramdisk/w29bench/ml_medium_%d.jsonl" % RECORDS
    if not os.path.exists(path):
        t0 = time.perf_counter()
        print("generating medium (%d records)..." % RECORDS, flush=True)
        from ml_data_gen import generate_data
        generate_data(path, RECORDS, variant="medium")
        print("  generated %.1fMB in %.0fs"
              % (os.path.getsize(path) / 2**20, time.perf_counter() - t0),
              flush=True)
    n_records = RECORDS
    moddir = tempfile.mkdtemp(prefix="w29fault_mod_")
    markdir = tempfile.mkdtemp(prefix="w29fault_mark_")
    sys.path.insert(0, moddir)

    clean_res = {}
    scale = RECORDS // BASE_RECORDS
    print("medium %dM, lines=%d (%d batches), kills calibrated to 5M "
          "schedule (x%d EVERY)" % (RECORDS // 1_000_000, LINES,
                                    N_BATCHES, scale),
          flush=True)
    POISON_IDX = N_BATCHES // 2  # mid-run deterministic poison batch
    MODES = sys.argv[2].split(",") if len(sys.argv) > 2 else (
        ("clean", "burst", "sustained", "segv-once", "poison"))
    ONLY_WORKERS = [int(x) for x in sys.argv[3].split(",")] \
        if len(sys.argv) > 3 else WORKERS
    NTRIALS = int(sys.argv[4]) if len(sys.argv) > 4 else TRIALS
    for workers in WORKERS:
        if workers not in ONLY_WORKERS:
            continue
        # Hold death counts constant vs the 5M run: 4x batches needs
        # 4x sparser candidates for the same ~W/2 deaths.
        every = max(1, scale * (2 * (BASE_RECORDS // LINES)) // workers)
        for mode in MODES:
            name = "w29f_%s_%dw" % (mode, workers)
            with open(os.path.join(moddir, name + ".py"), "w") as fh:
                fh.write(MOD_TMPL.format(
                    marker_dir=markdir, mode=mode, every=every,
                    burst_n=workers, poison_idx=POISON_IDX,
                    tail_n=workers, tail_segv_idx=N_BATCHES - 10,
                    n_batches=N_BATCHES))
            spec = name + ":payload"
            times, deaths, res = [], 0, None
            for _ in range(1 + NTRIALS):  # warmup + trials
                reset_markers(markdir)
                dt, res = run_pass(spec, path, workers)
                times.append(dt)
                deaths = count_markers(markdir)
            med = statistics.median(times[1:])
            rate = n_records / med
            if mode == "clean":
                clean_res[workers] = res
                ok = True
            elif mode == "poison":
                # Exactly the poison batch missing, all else identical.
                want = (clean_res[workers][:POISON_IDX]
                        + clean_res[workers][POISON_IDX + 1:])
                ok = (res == want)
            else:
                ok = (res == clean_res[workers])
            print("%-18s med=%.1fs trials=%s rate=%.0f rec/s "
                  "deaths=%d exact=%s"
                  % (name, med,
                     ",".join("%.1f" % t for t in times),
                     rate, deaths, ok), flush=True)
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
