#!/usr/bin/env python3
"""C0.7 gate 1: does one published slot always yield one complete frame?

ANSWER, MEASURED: NO. Kept as a runnable record of the sweep that decided
the design question, because the single measurement that motivated Option 2
(15 published / 15 recv / 15 emitted / 14 collected) was NOT sufficient.

Sweep: nodes {1,@2,@4} x workers {1,2,4} x lines {1,3,7}, 100-line input.

  nodes=1 (UMA)     frames == yielded, no expected side -- the drain audit
                     is never called on UMA, so there is nothing to compare.
  nodes=@2, @4      published_slots - observed_frames == 1, UNIFORMLY,
                     across every node count, worker count and batch size.

And filtered == 0 everywhere: the framer skips nothing. The extra
published slot is not a control frame being discarded -- it is the EOF
sentinel, which advances write_idx and NEVER emits an order packet.

Because the gap is a constant 1 regardless of node count (published is
101/35/16 identically for @2 and @4), it is one sentinel, not one per
node -- so it is not safely derivable from the topology either.

CONCLUSION: the packet/slot correspondence the reviewer conditioned Option 2
on does not hold. Per that stated condition, the fallback is the engine-side
DATA-slot count (Option 1).
"""
import sys, os, tempfile, itertools
sys.path.insert(0, '/mnt/ramdisk/forkrun/python')
import forkrun
Rm = sys.modules['forkrun.run']

def up(b): return b.copy()

def expected_slots(lib, nodes):
    import ctypes as C
    d = lib.fr_py_diag_node
    d.argtypes = [C.c_int, C.POINTER(C.c_uint64)]
    d.restype = C.c_int
    arr = (C.c_uint64 * 6)()
    total = 0
    for n in range(nodes):
        if d(n, arr) == 0:
            total += int(arr[0])
    return total

rows, bad = [], 0
nlines, tmpd = 100, tempfile.mkdtemp()
src = os.path.join(tmpd, 'in.txt')
with open(src, 'w') as fh:
    for i in range(nlines): fh.write('line%05d\n' % i)
inbytes = os.path.getsize(src)

for nodes, workers, lines, bytesb in itertools.product(
        [1, '@2', '@4'], [1, 2, 4], [1, 3, 7], [None, 8192]):
    nn = int(str(nodes).lstrip('@'))
    if workers > nn * 2: continue
    kw = {}
    if lines: kw['lines'] = lines
    if bytesb: kw['bytes'] = bytesb
    Rm.reset_frame_stats()
    try:
        out = forkrun.map(up, src, workers=workers, nodes=nodes,
                          order='index', **kw)
    except Exception as e:
        rows.append((nodes, workers, lines, bytesb, 'RAISED', '-', '-', False))
        bad += 1
        continue
    fs = Rm.frame_stats()
    ps = Rm.published_slots()
    exp = ps['total']
    outbytes = sum(len(r) for r in out)
    ok_bytes = (outbytes == inbytes)
    ok_frame = (exp is not None and exp == fs['complete'])
    rows.append((nodes, workers, lines, bytesb,
                 fs['complete'], fs['filtered'],
                 (exp if exp is not None else '-'),
                 (len(out) if exp == fs['complete'] else 'MISMATCH')))
    if not ok_bytes or not ok_frame:
        bad += 1

print("%-6s %-4s %-5s %-6s %-9s %-8s %-9s %s" % (
    'nodes','w','lines','bytes','frames','filt','published','match'))
for r in rows:
    print("%-6s %-4s %-5s %-6s %-9s %-8s %-9s %s" % (str(r[0]),r[1],r[2],
          str(r[3]),str(r[4]),str(r[5]),str(r[6]),str(r[7])))
print("\nconfigs=%d  anomalies=%d" % (len(rows), bad))
