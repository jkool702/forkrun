import os, sys, tempfile, threading, time
sys.path.insert(0, '/mnt/ramdisk/forkrun/python')
sys.path.insert(0, '/mnt/ramdisk/forkrun/python/tests')
import forkrun

PLUG = os.environ.get("PLUG", "/tmp/opencode/mlbench/ml_plugin_light.so")
SPEC = PLUG + ":ml_process_light"
N = int(os.environ.get("N", "2000"))
W = int(os.environ.get("W", "4"))
ND = int(os.environ.get("ND", "4"))
KIND = os.environ.get("K", "cr_stream")
PROBE = os.environ.get("PROBE", "0") == "1"

sys.modules["forkrun.run"]._execute_cleanroom = None  # placeholder


def pipe_source(n, delay=0.0):
    r, w = os.pipe()

    def run():
        buf = []
        for i in range(n):
            buf.append('{"eid":"e%d","uid":1,"iid":2,"ts":1700000000,'
                       '"et":"view","dev":"ios","dur":5}\n' % i)
            if len(buf) >= 500:
                os.write(w, "".join(buf).encode()); buf = []
            if delay:
                time.sleep(delay)
        if buf:
            os.write(w, "".join(buf).encode())
        os.close(w)

    th = threading.Thread(target=run, daemon=True)
    th.start()
    return r, th


def expected_bytes(n):
    # ml_process_light emits a fixed-size record per input record; get the
    # authoritative count from ONE in-process run rather than assuming.
    fd, p = tempfile.mkstemp(suffix=".jsonl")
    with os.fdopen(fd, "w") as fh:
        for i in range(n):
            fh.write('{"eid":"e%d","uid":1,"iid":2,"ts":1700000000,'
                     '"et":"view","dev":"ios","dur":5}\n' % i)
    os.environ["FORKRUN_CLEANROOM"] = "0"
    out = forkrun.map(SPEC, p, workers=W, nodes=ND, mode="plugin",
                      output="bytes", orchestrator=False)
    os.unlink(p)
    return sum(len(bytes(x)) for x in out)


def run_once(expect, probe=False):
    os.environ["FORKRUN_CLEANROOM"] = "1" if KIND == "cr_stream" else "0"
    orch = False if KIND == "cr_stream" else True
    taken = [False]
    if probe:
        R = sys.modules["forkrun.run"]
        real = R._execute_cleanroom_stream
        def spy(*a, **k):
            taken[0] = True
            return real(*a, **k)
        R._execute_cleanroom_stream = spy
    r, th = pipe_source(N)
    tot = 0
    try:
        for blob in forkrun.stream(SPEC, r, mode="plugin", workers=W,
                                   nodes=ND, streaming=True,
                                   orchestrator=orch):
            tot += len(bytes(blob))
    finally:
        th.join(timeout=60)
        try:
            os.close(r)
        except OSError:
            pass
        if probe:
            R = sys.modules["forkrun.run"]
            R._execute_cleanroom_stream = real
    return tot, taken[0]


if __name__ == "__main__":
    expect = expected_bytes(N)
    if PROBE:
        tot, taken = run_once(expect, probe=True)
        print("PROBE kind=%s launcher_taken=%s bytes=%d expect=%d %s"
              % (KIND, taken, tot, expect, "OK" if tot == expect else "MISMATCH"))
        if KIND == "cr_stream" and not taken:
            print("FATAL: cleanroom streaming hook did not fire -- this "
                  "config would prove nothing"); sys.exit(2)
        sys.exit(0 if tot == expect else 1)
    tot, _ = run_once(expect)
    print("%s W=%d nodes=%d bytes=%d" % (KIND, W, ND, tot))
