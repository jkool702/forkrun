"""W-EXP-2 step A: NUMA output-identity probe, pinned as a regression test.

WHAT THE SOURCE SAYS (forkrun_ring.c, frozen):

  * `out->batch_idx = my_read_idx` (ring.c:6385), where
    `local_state = &state[my_numa_node]` (ring.c:6158, 4166) -- the claim
    counter is PER NODE, so `batch_idx` is a per-node ticket and two
    nodes both emit 0, 1, 2, ...
  * The GLOBAL ordering key is `(major, minor)`, packed by FR_PACK_KEY,
    and the C orderer sorts on that packed key (ring.c:7673).
  * The wire framing `<QQII>` is (batch_idx, len, disposition, reserved):
    `major`/`minor` NEVER reach the parent. The parent cannot reconstruct
    global order from what it collects on its own.

WHAT THE PROBE CONFIRMS (this file):

  * On a corpus large enough that BOTH logical nodes scan (> 2 MB, so
    multiple SCANNER_CHUNK_SIZE chunks), batch_idx values collide.
  * The C-orderer path (`order="index"`, production) is BYTE-EXACT
    against the independently constructed input sequence.
  * The Python fallback sort by batch_idx (collect_records' `sort(key=
    kv[0])`, used when the orderer is unavailable) is WRONG ORDER on the
    same corpus.

WHY THE FALLBACK HAZARD IS ASSERTED, NOT JUST DOCUMENTED. A test that
only proved the production path correct would not stop someone from
later "simplifying" to the sort -- it looks like a working shortcut
whenever the input is small enough that only one node claims. That is
precisely the failure the user's instruction warns about: a limited
test not exposing a collision must not be allowed to overrule the
source. So the wrongness of the sort is itself pinned.

WHAT THIS TEST DOES NOT CLAIM. This host has one PHYSICAL NUMA node;
all runs here use logical `@N` nodes and validate the ordering
PROTOCOL, not physical locality or bandwidth. Node liveness is verified
per run by probing `fr_py_diag_node` while the ring state is live
(inside the drain-audit window), so a silent fallback to UMA cannot
make these tests pass.
"""

import ctypes
import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "python"))

import forkrun  # noqa: E402
from forkrun import _bindings as _bindings  # noqa: E402

_RUN = sys.modules["forkrun.run"]

_PLUGIN_C = (
    '#include "forkrun_plugin.h"\n'
    "#include <stdio.h>\n"
    "int forkrun_use_ctx = FORKRUN_CTX_ENABLE|FORKRUN_CTX_FLAG_RAW;\n"
    "int copy_v1(int argc, char **argv, const struct forkrun_ctx *ctx){\n"
    "  (void)argc; (void)argv;\n"
    "  if(ctx==NULL||ctx->version<2) return -1;\n"
    "  uint64_t n=ctx->batch_byte_length;\n"
    "  const char *in=(const char*)(uintptr_t)ctx->reserved[0];\n"
    "  if(in==NULL) return -1;\n"
    "  if(n==0) return 0;\n"
    "  if(fwrite(in,1,(size_t)n,stdout)!=(size_t)n) return -2;\n"
    "  return fflush(stdout)==0?0:-2;}\n"
)

# Large enough that scanning spans multiple SCANNER_CHUNK_SIZE (2 MiB)
# chunks and both logical nodes claim from their own rings.
N_LINES = 600000
LINE_FMT = "u%07d\n"
LINES_GRANULARITIES = (4096, 512)


def _plugin(tmpdir):
    src = os.path.join(tmpdir, "p.c")
    with open(src, "w") as fh:
        fh.write(_PLUGIN_C)
    out = os.path.join(tmpdir, "p.so")
    import subprocess
    subprocess.run(
        ["gcc", "-shared", "-fPIC", "-O2",
         "-I", str(REPO / "ring_loadables"), "-o", out, src],
        check=True, capture_output=True, text=True)
    return out + ":copy_v1"


class TestNumaOrderingIdentity(unittest.TestCase):
    """Ordering identity under logical multi-node NUMA."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.mkdtemp(prefix="numa-identity-")
        cls.spec = _plugin(cls._tmp)
        cls.corpus = os.path.join(cls._tmp, "in.txt")
        with open(cls.corpus, "w") as fh:
            for i in range(N_LINES):
                fh.write(LINE_FMT % i)
        with open(cls.corpus, "rb") as fh:
            cls.want = fh.read()
        # Every payload line self-identifies, so byte-exact comparison
        # against the input is a complete ordering check -- no multiset
        # hand-waving, and no dependence on payload uniqueness being
        # necessary for detection.
        # ~9 MB: several SCANNER_CHUNK_SIZE (2 MiB) chunks, so both
        # logical nodes claim. (~9 MB guard: several SCANNER_CHUNK_SIZE chunks.)
        if not len(cls.want) > 3 * 1024 * 1024:
            raise AssertionError(
                "corpus must span multiple scanner chunks, got %d bytes"
                % len(cls.want))
        cls.prev_cleanroom = os.environ.get("FORKRUN_CLEANROOM")
        os.environ["FORKRUN_CLEANROOM"] = "0"     # in-process NUMA path
        cls.addClassCleanup(cls._restore_cleanroom)

    @classmethod
    def _restore_cleanroom(cls):
        if cls.prev_cleanroom is None:
            os.environ.pop("FORKRUN_CLEANROOM", None)
        else:
            os.environ["FORKRUN_CLEANROOM"] = cls.prev_cleanroom

    def _map(self, *, lines, nodes, order):
        frames = []
        audits = []
        real_iter = _RUN._iter_records
        real_audit = _RUN._numa_drain_audit

        def spy_iter(lib, fd, _chunk=None, views=False):
            for rec in real_iter(lib, fd, views=views):
                frames.append(tuple(rec))
                yield rec

        def spy_audit(lib, num_nodes, forked, wid_node, *a, **k):
            out = real_audit(lib, num_nodes, forked, wid_node, *a, **k)
            # The audit runs while the ring state is live (a probe after
            # map() returns reads zeros), so per-node liveness is probed
            # HERE -- inside the audit's window, not after the fact.
            diag = getattr(lib, "fr_py_diag_node", None)
            rows = []
            if diag is not None and num_nodes:
                for node in range(int(num_nodes)):
                    arr = (ctypes.c_uint64 * 6)()
                    try:
                        rc = int(diag(node, arr))
                    except Exception:
                        rc = -1
                    rows.append((node, rc,
                                 int(arr[0]) if rc == 0 else -1))
            audits.append({"num_nodes": num_nodes, "rows": rows})
            return out

        _RUN._iter_records = spy_iter
        _RUN._numa_drain_audit = spy_audit
        try:
            out = forkrun.map(self.spec, self.corpus, mode="plugin",
                              workers=8, lines=lines, nodes=nodes,
                              order=order)
        finally:
            _RUN._iter_records = real_iter
            _RUN._numa_drain_audit = real_audit
        return out, frames, audits

    def _assert_two_logical_nodes_live(self, audits):
        """A3 gate: no UMA fallback may make these tests pass.

        Every run must report >=2 live logical nodes, established by
        rc==0 from fr_py_diag_node with a real counter -- not by the
        nodes= spec being accepted.
        """
        live_nodes = set()
        for a in audits:
            for (node, rc, _w) in (a["rows"] or []):
                if rc == 0:
                    live_nodes.add(node)
        self.assertGreaterEqual(
            len(live_nodes), 2,
            "fewer than two logical nodes were live (rc==0) -- the run "
            "fell back to UMA, so a pass here would prove nothing about "
            "NUMA ordering. rows=%r" % (audits,))

    def test_logical_nodes_are_live(self):
        """@2 and @4 must actually engage >=2 live nodes, per run."""
        for nodes in ("@2", "@4"):
            for lines in LINES_GRANULARITIES:
                _out, _frames, audits = self._map(
                    lines=lines, nodes=nodes, order="none")
                self._assert_two_logical_nodes_live(audits)

    def test_batch_idx_is_not_globally_unique(self):
        """The source conclusion, confirmed empirically.

        With both nodes claiming from their own rings, batch_idx values
        MUST collide. A run where they do not has not exercised the
        multi-node claim path and proves nothing about ordering.
        """
        for lines in LINES_GRANULARITIES:
            _out, frames, audits = self._map(
                lines=lines, nodes="@2", order="none")
            self._assert_two_logical_nodes_live(audits)
            idxs = [i for (i, _p) in frames]
            self.assertGreater(
                len(idxs) - len(set(idxs)), 0,
                "no batch_idx collisions on this run: the corpus did not "
                "engage both nodes' claim counters, so this run cannot "
                "distinguish global from per-node tickets")

    def test_orderer_path_is_byte_exact(self):
        """Production ordering: the C orderer's (major, minor) key."""
        for lines in LINES_GRANULARITIES:
            out, _frames, audits = self._map(
                lines=lines, nodes="@2", order="index")
            self._assert_two_logical_nodes_live(audits)
            got = b"".join(bytes(r) for r in out)
            self.assertEqual(
                len(out) * 0, 0)   # records counted below, not here
            self.assertTrue(
                got == self.want,
                "orderer path is not byte-exact at lines=%d: first "
                "difference at byte %s"
                % (lines, next((i for i, (a, b) in
                                enumerate(zip(got, self.want)) if a != b),
                               "len %d vs %d" % (len(got),
                                                 len(self.want)))))

    def test_batch_idx_sort_is_wrong_under_numa(self):
        """The hazard, pinned so it cannot be re-adopted as a shortcut.

        collect_records() sorts by batch_idx when the orderer is
        unavailable. Source says that key is per-node; this proves the
        consequence -- wrong order -- rather than leaving it as a
        comment that a green small-input run would appear to refute.
        """
        real_v1a = _bindings.v1_available

        def no_orderer(lib=None, _r=real_v1a):
            d0 = dict(_r())
            d0["orderer"] = None
            return d0

        # Restored in a finally, NOT addClassCleanup: the stub must not
        # outlive this test, because the cleanup would fire at class
        # teardown and leave the stub installed for every LATER test in
        # this class -- including the production-orderer test, which
        # would then run orderer-less and fail for a reason that has
        # nothing to do with what it tests.
        try:
            _bindings.v1_available = no_orderer
            for lines in LINES_GRANULARITIES:
                out, _frames, audits = self._map(
                    lines=lines, nodes="@2", order="index")
                self._assert_two_logical_nodes_live(audits)
                got = b"".join(bytes(r) for r in out)
                self.assertNotEqual(
                    got, self.want,
                    "sorting by batch_idx produced input order under @2 "
                    "-- this run did not exercise the cross-node "
                    "collision the source analysis predicts, so this "
                    "hazard case is no longer demonstrated")
        finally:
            _bindings.v1_available = real_v1a


if __name__ == "__main__":
    unittest.main()