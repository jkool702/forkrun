"""W-PY21-B phase-time benchmark: legacy split path vs C commit path."""
import os
import statistics
import struct
import sys
import tempfile
import time

sys.path.insert(0, "/mnt/ramdisk/forkrun/python")

import forkrun  # noqa: E402

WORKERS = 8
TRIALS = 3


def noop(batch):
    return None


def upper(batch):
    return bytes(batch.data).upper()


def gen_lines(path, n):
    with open(path, "w") as fh:
        for i in range(n):
            fh.write("line %06d\n" % i)


def med(fn, trials=TRIALS):
    ts = []
    for _ in range(trials):
        t0 = time.perf_counter()
        out = fn()
        ts.append((time.perf_counter() - t0, out))
    ts.sort(key=lambda t: t[0])
    return ts[len(ts) // 2]


def lines_of(path):
    with open(path, "rb") as fh:
        return sum(1 for _ in fh)


def bench_map(path, nlines, payload, label, **kw):
    rows = {}
    for tag, env in (("new", None), ("legacy", "1")):
        if env is None:
            os.environ.pop("FORKRUN_NO_V1", None)
        else:
            os.environ["FORKRUN_NO_V1"] = "1"
        dt, res = med(lambda: forkrun.map(payload, path, workers=WORKERS,
                                          **kw))
        rate = nlines / dt
        rows[tag] = (dt * 1000, rate, len(res))
        print("  %-6s %-28s %8.1f ms  %10.3f M lines/s  (%d records)" %
              (tag, label, dt * 1000, rate / 1e6, len(res)), flush=True)
    os.environ.pop("FORKRUN_NO_V1", None)
    new_ms, new_rate, _ = rows["new"]
    leg_ms, leg_rate, _ = rows["legacy"]
    print("  --> speedup: %.2fx  (%.1f%% lines/s gain)" %
          (leg_ms / new_ms, 100 * (new_rate - leg_rate) / leg_rate),
          flush=True)
    return rows


def bench_parse():
    from forkrun.run import _parse_records_c, _split_records
    H = struct.Struct("<QQ")
    # ~48MB framed blob, mixed record sizes + truncated tail
    parts = []
    total = 0
    i = 0
    while total < 48 << 20:
        s = (i * 7919) % 3000 + 1
        parts.append(H.pack(i, s) + b"y" * s)
        total += 16 + s
        i += 1
    blob = b"".join(parts) + b"tail-bytes"
    print("  blob: %.1f MB, %d records" % (len(blob) / 2**20, i),
          flush=True)
    t0 = time.perf_counter()
    for _ in range(3):
        py = _split_records(blob)[0]
    py_ms = (time.perf_counter() - t0) / 3 * 1000
    t0 = time.perf_counter()
    for _ in range(3):
        c = _parse_records_c(blob)
    c_ms = (time.perf_counter() - t0) / 3 * 1000
    assert len(py) == len(c) and py[0] == c[0] and py[-1] == c[-1]
    print("  python _split_records: %8.1f ms" % py_ms, flush=True)
    print("  c descriptors+slicing: %8.1f ms  (%.2fx)" % (c_ms, py_ms / c_ms),
          flush=True)


def bench_spill(path):
    from forkrun.run import _spill_to_memfd
    size = os.path.getsize(path)
    print("  file: %.1f MB" % (size / 2**20,), flush=True)
    t0 = time.perf_counter()
    for _ in range(3):
        src = os.open(path, os.O_RDONLY)
        try:
            _, sz = _spill_to_memfd(src)
        finally:
            os.close(src)
    c_ms = (time.perf_counter() - t0) / 3 * 1000
    assert sz == size
    CH = 1 << 20

    def old_loop():
        memfd = os.memfd_create("bench_old")
        sz2 = 0
        src = os.open(path, os.O_RDONLY)
        try:
            while True:
                chunk = os.pread(src, CH, sz2)
                if not chunk:
                    break
                off = sz2
                view = memoryview(chunk)
                while view:
                    n = os.pwrite(memfd, view, off)
                    view = view[n:]
                    off += n
                    sz2 += n
        finally:
            os.close(src)
            os.close(memfd)
        return sz2
    t0 = time.perf_counter()
    for _ in range(3):
        assert old_loop() == size
    py_ms = (time.perf_counter() - t0) / 3 * 1000
    print("  python pread/pwrite loop: %8.1f ms" % py_ms, flush=True)
    print("  c copy_range+spill:       %8.1f ms  (%.2fx)" % (c_ms, py_ms / c_ms),
          flush=True)


def main():
    print("forkrun %s engine %s workers=%d" %
          (forkrun.__version__, forkrun.__engine_version__, WORKERS))
    tmp = tempfile.mkdtemp(prefix="w21b_")
    p1m = os.path.join(tmp, "in_1m.txt")
    gen_lines(p1m, 1_000_000)
    n = lines_of(p1m)
    print("== end-to-end map, 1M lines ==")
    bench_map(p1m, n, noop, "noop (dispatch/commit only)")
    bench_map(p1m, n, upper, "upper transform")
    bench_map(p1m, n, upper, "upper ordered", order="index")
    print("== parse microbench ==")
    bench_parse()
    big = os.path.join(tmp, "in_big.txt")
    gen_lines(big, 10_000_000)  # ~130MB
    print("== spill microbench ==")
    bench_spill(big)


if __name__ == "__main__":
    main()
