#!/usr/bin/env python3
"""Separate TRANSIENT in-flight buffering from a Python-object LEAK (TD-13).

WHY THIS EXISTS, separately from `_streaming_rss_probe.py`
---------------------------------------------------------
`_streaming_rss_probe.py` measures CURRENT RSS sampled inside the consumer
loop. That is the right instrument for "how much resident memory does the
streaming parent hold at peak", and it is what produced TD-13's 0.50x
figure.

It CANNOT, by itself, answer "is that retained or merely in flight?".
A single RSS curve is consistent with three very different situations:

  1. live output objects still referenced by the parent (a real leak),
  2. drain/reassembly buffering that will be released (transient), and
  3. freed arenas the allocator has not returned to the OS (pure noise).

TD-13's register entry said exactly this -- that the probe "cannot by
itself separate" those three -- and left the mechanism open. This probe
separates them by adding an INSTRUMENT that does not depend on RSS:

  * `tracemalloc`, started BEFORE the workload, so it observes the
    relevant allocations. Its "currently allocated" figure after a full
    drain is the load-bearing number: it is a Python-tracked live-bytes
    count, not a page count.
  * a live-object census, as a SECONDARY signal only.
  * `gc.collect()` around the final reading, so "freed but not yet
    collected" is distinguishable from "still referenced".
  * `/proc/self/smaps_rollup` for the resident figure, because the kernel
    documents `/proc/self/statm`'s resident numbers as potentially
    inaccurate (TD-13's "post-drain RSS" readings turned out to be
    allocator-dependent: sometimes baseline+45 MB, sometimes baseline+0 MB,
    with identical tracemalloc).

A CAVEAT ON THE CENSUS, stated so it is not over-read
------------------------------------------------------
`gc.get_objects()` returns only objects the CYCLIC garbage collector
tracks. **Not every `bytes`/`bytearray`/`memoryview` is GC-tracked**, so
a census count of zero does NOT prove the absence of every live bytes
allocation. It is corroboration, not proof.

The number to actually trust is `tracemalloc`'s post-drain live bytes,
because tracemalloc hooks the allocator and counts every tracked
allocation regardless of GC participation. **If these two disagree,
tracemalloc wins.**

Reproduce (from the repo root):

    python3 python/tests/_streaming_memory_probe.py --lines 1600000 --delay 0.01
    python3 python/tests/_streaming_memory_probe.py --lines 800000 --order index

This is a DIAGNOSTIC, not a test. It asserts nothing and is not collected
by the unittest discovery pattern (leading underscore), so it cannot make
the suite pass or fail. It exists so the strongest TD-13 evidence is not
tied to a scratch file in /tmp.
"""
import argparse
import gc
import json
import os
import sys
import tempfile
import time
import tracemalloc

_HERE = os.path.dirname(os.path.abspath(__file__))
# _HERE is <repo>/python/tests; its parent holds the forkrun PACKAGE.
sys.path.insert(0, os.path.dirname(_HERE))
sys.path.insert(0, _HERE)


def rss_kb():
    """Resident set size (KiB) from /proc/self/statm.

    Cheap and used for the sampled PEAK, where a single accurate reading
    does not matter. The post-drain figure uses smaps_rollup instead --
    see the module docstring.
    """
    try:
        with open("/proc/self/statm", "rb") as fh:
            return int(fh.read().split()[1]) * (os.sysconf("SC_PAGE_SIZE") // 1024)
    except (OSError, IndexError, ValueError):
        return None


def smaps_rollup():
    """Authoritative resident/dirty figures from /proc/self/smaps_rollup."""
    out = {}
    try:
        with open("/proc/self/smaps_rollup") as fh:
            for line in fh:
                key, _, rest = line.partition(":")
                parts = rest.split()
                if len(parts) >= 2 and parts[1] == "kB":
                    out[key.strip()] = int(parts[0])
    except OSError:
        pass
    return out


def census_record_objects():
    """SECONDARY signal only -- GC-tracked objects only. See the docstring:
    a zero here does not prove every bytes allocation is gone."""
    n = 0
    for obj in gc.get_objects():
        if isinstance(obj, (bytes, bytearray, memoryview)):
            n += 1
    return n


def write_corpus(path, n):
    from _helpers import write_lines
    write_lines(path, n)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--lines", type=int, default=1600000)
    ap.add_argument("--amp", type=int, default=5,
                    help="payload output multiplier")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--order", default="none")
    ap.add_argument("--orchestrator", default="0")
    ap.add_argument("--delay", type=float, default=0.001)
    args = ap.parse_args(argv)

    tmp = tempfile.mkdtemp(prefix="td13-")
    path = os.path.join(tmp, "in.txt")
    write_corpus(path, args.lines)
    amp = args.amp

    def amplify(batch):
        return bytes(batch.data) * amp

    import forkrun

    # tracemalloc starts BEFORE the workload so the relevant allocations
    # are observed. Starting it later would silently understate.
    tracemalloc.start()

    base = rss_kb()
    peak = base
    out_bytes = 0
    blobs = 0

    for blob in forkrun.stream(amplify, path, workers=args.workers,
                               nodes=1,
                               orchestrator=args.orchestrator == "1",
                               order=args.order):
        blobs += 1
        out_bytes += len(blob)
        cur = rss_kb()
        if cur is not None and cur > peak:
            peak = cur
        # The consumer DISCARDS every record. Any retention observed is
        # therefore the producer's, not the caller's.
        del blob
        if args.delay:
            time.sleep(args.delay)

    pre_gc_rss = rss_kb()
    census_pre = census_record_objects()
    tm_pre, _peak_tm = tracemalloc.get_traced_memory()

    gc.collect()

    post_gc_rss = rss_kb()
    census_post = census_record_objects()
    tm_post, _ = tracemalloc.get_traced_memory()
    roll = smaps_rollup()

    try:
        os.unlink(path)
        os.rmdir(tmp)
    except OSError:
        pass

    result = {
        "lines": args.lines,
        "amp": amp,
        "order": args.order,
        "workers": args.workers,
        "delay": args.delay,
        "blobs": blobs,
        "out_bytes": out_bytes,
        "baseline_kb": base,
        "peak_kb": peak,
        "peak_growth_kb": None if base is None else peak - base,
        "peak_ratio": (None if base is None or not out_bytes
                       else (peak - base) * 1024 / out_bytes),
        "rss_final_pre_gc_kb": pre_gc_rss,
        "rss_final_post_gc_kb": post_gc_rss,
        # THE LOAD-BEARING NUMBER: Python-tracked bytes still live after a
        # complete drain. Compare against peak_growth_kb. If peak is tens
        # of MB and this is tens of KB, the peak was transient in-flight
        # data, not retained output.
        "tracemalloc_live_pre_gc": tm_pre,
        "tracemalloc_live_post_gc": tm_post,
        # Corroboration only -- GC-tracked objects only.
        "census_record_objects_pre_gc": census_pre,
        "census_record_objects_post_gc": census_post,
        "census_is_corroboration_only": True,
        "smaps_rss_kb": roll.get("Rss"),
        "smaps_anonymous_kb": roll.get("Anonymous"),
        "smaps_private_dirty_kb": roll.get("Private_Dirty"),
    }
    print(json.dumps(result, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())