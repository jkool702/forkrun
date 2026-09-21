"""Resume/checkpoint orchestration for C-orderer paths (W-PY22).

The engine owns the resume ledger (TRACK_COMPLETED_BATCH in
ring_order_main); this module is the Python-side glue:

- path gating (resume is supported ONLY where a live C orderer /
  tracker exists — anything else fails loudly, never silently),
- resume begin (parse + safety + fr_py_set_resume_state, post-init),
- abort choreography (quiesce -> reap -> snapshot -> publish ->
  destroy), with bounded waits and a fail-closed sidecar for the
  aborted run's already-committed output (map/collect paths).

SEMANTIC CONTRACT (engine commit vs consumer observation):
  ENGINE COMMIT is exactly-once — the C orderer's committed output
  frontier (byte coordinates) survives abort+resume without
  duplication (successive checkpoints accumulate via the orderer's
  bootstrap). PYTHON CONSUMPTION is not — a crash between engine
  commit and Python observation means the checkpoint skips bytes
  the caller never received. Applications needing end-to-end
  exactly-once must persist consumed results themselves.

All coordinates are BYTES on the Universal Coordinate Plane
(horizon = contiguous committed input offset; jagged = committed
intervals beyond it) — never batch numbers.
"""

from __future__ import annotations

import os
import sys
import time

from ._checkpoint import (DEFAULT_CHECKPOINT_FILE, CheckpointState,
                          check_checkpoint_safety, parse_checkpoint,
                          snapshot_from_engine, write_checkpoint)

# Sidecar suffix: framed engine-committed output of aborted runs,
# stored next to the checkpoint. map() prepends it on a successful
# resumed run (sorted by batch_idx) so abort+resume yields complete
# output. stream() never uses sidecars (the consumer owns everything
# yielded live; unyielded coll bytes are the documented consumer gap).
SIDECAR_SUFFIX = ".coll"

# Bounded waits in the choreography (a payload-stuck worker ignores
# the fire alarm; the orderer drains a pipe — both get SIGKILL on
# expiry, and the ledger snapshot covers whatever committed).
WORKER_REAP_TIMEOUT = 3.0
ORDERER_REAP_TIMEOUT = 10.0


def path_has_c_orderer(*, order, orchestrator, mode, collect=True,
                       splice=False):
    """True only where a live C orderer/tracker exists.

    The resume ledger lives in ring_order_main. Without a C orderer
    there is no tracker and no meaningful checkpoint: map() without
    orchestrator+index does a Python sort, run() never collects,
    splice workers never send OrderPackets.
    """
    if mode == "splice" or splice:
        return False
    if order != "index":
        return False
    if not orchestrator:
        return False
    if not collect:
        return False
    return True


def require_resume_path(where, *, order, orchestrator, mode,
                        collect=True, splice=False, num_nodes=1):
    """Gate resume=/checkpoint_file= to C-orderer paths (fail loudly).

    Raises RuntimeError naming the exact unsupported combination.
    num_nodes > 1 (NUMA multi-node) is rejected: per-node rings make
    the global byte frontier unsafe to resume in v3.6.0.
    """
    if num_nodes != 1:
        raise RuntimeError(
            "%s: resume/checkpoint_file on multi-node NUMA paths "
            "is not supported in v3.6.0 (num_nodes=%r); use a "
            "single-node run" % (where, num_nodes))
    if mode == "splice" or splice:
        raise RuntimeError(
            "%s: resume/checkpoint_file requires a C-orderer-backed "
            "path, but mode='splice' workers never send OrderPackets "
            "(no tracker exists)" % (where,))
    if order != "index":
        raise RuntimeError(
            "%s: resume/checkpoint_file requires order='index' with "
            "a C orderer (got order=%r); the unordered/Python-sort "
            "paths have no resume ledger" % (where, order))
    if not orchestrator:
        raise RuntimeError(
            "%s: resume/checkpoint_file requires orchestrator=True "
            "(reactor supervision spawns the C orderer)" % (where,))
    if not collect:
        raise RuntimeError(
            "%s: resume/checkpoint_file requires a collecting path "
            "(map()/stream()); run() has no C orderer" % (where,))


def resolve_checkpoint_dest(checkpoint_file, resume_path):
    """Checkpoint destination: explicit file wins, else the resume
    source (cumulative overwrite), else the default file."""
    if checkpoint_file:
        return checkpoint_file
    if resume_path:
        return resume_path
    return DEFAULT_CHECKPOINT_FILE


def resume_begin(lib, resume_path, *, order, orchestrator, mode,
                 collect=True, splice=False, num_nodes=1):
    """Begin a resumed run: gate + parse + safety + engine state.

    Call AFTER fr_py_init (which zeroes the ledger) and BEFORE the
    scan/worker forks. Returns the CheckpointState, or None when no
    resume was requested. Raises FileNotFoundError (missing file),
    ValueError (malformed checkpoint), RuntimeError (unsafe file,
    unsupported path, engine failure) — always before any fork.
    """
    if resume_path is None:
        return None
    require_resume_path("resume=", order=order,
                        orchestrator=orchestrator, mode=mode,
                        collect=collect, splice=splice,
                        num_nodes=num_nodes)
    state = parse_checkpoint(resume_path)
    ok, warnings = check_checkpoint_safety(resume_path)
    if not ok:
        raise RuntimeError(
            "refusing to resume from unsafe checkpoint %r: %s"
            % (resume_path, "; ".join(warnings)))
    for warning in warnings:
        try:
            print("forkrun [WARN]: %s" % warning, file=sys.stderr)
        except Exception:
            pass
    _set_engine_state(lib, state)
    return state


def _set_engine_state(lib, state):
    """Push a CheckpointState into the engine (typed, no argv)."""
    from ._bindings import FrPyInterval

    n = len(state.jagged)
    arr = None
    if n:
        arr = (FrPyInterval * n)(
            *[FrPyInterval(s, e) for s, e in state.jagged])
    set_state = getattr(lib, "fr_py_set_resume_state", None)
    if set_state is None:
        raise RuntimeError(
            "resume= needs fr_py_set_resume_state — rebuild the "
            "substrate ('make -f Makefile.substrate python-substrate')")
    rc = set_state(state.horizon, state.stdout_bytes, arr, n)
    if rc == -1:
        raise RuntimeError(
            "resume state set with no live engine "
            "(resume must follow fr_py_init)")
    if rc != 0:
        raise RuntimeError(
            "failed to set resume state (rc=%d)" % (rc,))


def _waitpid_bounded(pid, timeout):
    """Blocking reap with a deadline; SIGKILL on expiry, then reap.

    Returns (reaped, status-or-None). Never raises.
    """
    if pid is None or pid <= 0:
        return False, None
    deadline = time.monotonic() + max(0.0, timeout)
    while True:
        try:
            wpid, status = os.waitpid(pid, os.WNOHANG)
        except ChildProcessError:
            return True, None
        except OSError:
            return False, None
        if wpid == pid:
            return True, status
        if time.monotonic() >= deadline:
            break
        time.sleep(0.02)
    try:
        os.kill(pid, 9)
    except OSError:
        pass
    try:
        _, status = os.waitpid(pid, 0)
        return True, status
    except (ChildProcessError, OSError):
        return False, None


def _read_fd_all(fd):
    """pread a memfd from 0 to current end (shared description)."""
    try:
        size = os.fstat(fd).st_size
    except OSError:
        return b""
    chunks = []
    off = 0
    while off < size:
        try:
            chunk = os.pread(fd, min(size - off, 1 << 20), off)
        except OSError:
            break
        if not chunk:
            break
        chunks.append(chunk)
        off += len(chunk)
    return b"".join(chunks)


def _write_file_atomic(path, data):
    """Atomic bytes publication (tmp -> fsync -> chmod 600 -> rename)."""
    tmp_path = path + ".tmp"
    try:
        with open(tmp_path, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp_path, 0o600)
        os.rename(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _publish_sidecar(dest_coll, resume_src, coll_fd):
    """Publish the cumulative aborted-run output sidecar.

    combined = previous sidecar (next to the resume source, if any)
    + current collection bytes (framed streams concatenate). Empty
    combined output leaves any existing sidecar untouched (a
    None-payload run commits no output; the old sidecar stays valid
    under the cumulative checkpoint). Atomic on write.
    """
    parts = []
    if resume_src:
        src_coll = resume_src + SIDECAR_SUFFIX
        if os.path.exists(src_coll):
            try:
                with open(src_coll, "rb") as fh:
                    parts.append(fh.read())
            except OSError:
                pass
    if coll_fd is not None and coll_fd >= 0:
        parts.append(_read_fd_all(coll_fd))
    combined = b"".join(parts)
    if not combined:
        return False
    _write_file_atomic(dest_coll, combined)
    return True


def checkpoint_on_abort(lib, *, state, orderer_pid, order_w,
                         coll_fd, use_orderer, collect,
                         resume_src, checkpoint_file, engine_live):
    """Abort choreography: quiesce -> reap -> snapshot -> publish.

    Runs ONLY when the engine is live on a C-orderer path that was
    armed with resume= or checkpoint_file=. Ordering: abort (wake
    claim-gated workers/scanner) -> bounded worker reap (their
    order_w copies close on exit) -> close parent order_w (orderer
    EOF) -> bounded orderer reap (ledger final) -> seqlock snapshot
    (BEFORE destroy — the ledger lives in g_state) -> atomic
    sidecar (collect paths) -> atomic checkpoint publish.

    Skips silently (False) when unarmed, unsupported, or with no
    useful progress (horizon 0 and no jagged). Never raises: an
    abort path must not turn a sick pipeline into a second failure
    (the original exception keeps propagating).
    """
    if not engine_live or not use_orderer:
        return False
    if resume_src is None and checkpoint_file is None:
        return False
    dest = resolve_checkpoint_dest(checkpoint_file, resume_src)
    try:
        try:
            lib.fr_py_abort()
        except Exception:
            pass
        if state is not None:
            try:
                slots = list(getattr(state, "workers", {}).values())
            except Exception:
                slots = []
            for slot in slots:
                try:
                    pid = getattr(slot, "pid", None)
                    alive = getattr(slot, "alive", False)
                except Exception:
                    continue
                if pid and alive:
                    _waitpid_bounded(pid, WORKER_REAP_TIMEOUT)
        if order_w is not None and order_w >= 0:
            try:
                os.close(order_w)
            except OSError:
                pass
        if orderer_pid:
            _waitpid_bounded(orderer_pid, ORDERER_REAP_TIMEOUT)
        snap = snapshot_from_engine(lib)
        if snap is None or (snap.horizon == 0 and not snap.jagged):
            return False
        if collect and coll_fd is not None and coll_fd >= 0:
            try:
                _publish_sidecar(dest + SIDECAR_SUFFIX, resume_src,
                                 coll_fd)
            except Exception as exc:
                # Fail-closed: without the sidecar the checkpoint
                # would skip output the caller can never recover
                # (map/collect paths). The previous checkpoint
                # survives (atomicity) — report and stop.
                try:
                    print("forkrun: checkpoint sidecar failed "
                          "(%s); previous checkpoint preserved"
                          % (exc,), file=sys.stderr)
                except Exception:
                    pass
                return False
        write_checkpoint(dest, snap)
        try:
            print("forkrun: checkpoint written to %s "
                  "(engine committed frontier: %d bytes%s)" % (
                      dest, snap.horizon,
                      (", %d interval(s)" % len(snap.jagged))
                      if snap.jagged else ""),
                  file=sys.stderr)
            print("forkrun: to resume: re-run with resume=%r"
                  % (dest,), file=sys.stderr)
        except Exception:
            pass
        return True
    except Exception as exc:
        try:
            print("forkrun: checkpoint unavailable (%s)" % (exc,),
                  file=sys.stderr)
        except Exception:
            pass
        return False


def consume_sidecar(resume_src, records):
    """Prepend a resumed run's sidecar output (map/collect success).

    records: [(batch_idx, blob)] from the resumed run (already
    ordered). Returns sidecar ++ current (CONCATENATION, not a
    re-sort).

    Why not sort by batch_idx: indices restart at 0 in every fresh
    engine, so the resumed run's tail records (idx 0,1,2, ...) would
    interleave with the sidecar's original indices (sorting them is
    corruption, not ordering — observed in testing). Within each
    run, idx order already equals byte order, so concatenation is
    exactly byte-ordered when the abort quiesced contiguously (the
    common case: empty jagged); with jagged commits the new output
    appends after committed output (complete and duplicate-free,
    but not globally index-ordered — the documented resume contract:
    engine commit is exactly-once, cross-run index order is not).

    Consumes (deletes) the sidecar: its bytes are now delivered
    exactly once. No sidecar -> records unchanged. Never raises (a
    corrupt sidecar warns and yields the current records).
    """
    if not resume_src:
        return records
    path = resume_src + SIDECAR_SUFFIX
    try:
        with open(path, "rb") as fh:
            blob = fh.read()
    except OSError:
        return records
    try:
        from .run import _parse_records
        side = _parse_records(blob)
    except Exception as exc:
        try:
            print("forkrun [WARN]: checkpoint sidecar %r unreadable "
                  "(%s); continuing with current run output only"
                  % (path, exc), file=sys.stderr)
        except Exception:
            pass
        return records
    merged = list(side) + list(records)
    try:
        os.unlink(path)
    except OSError as exc:
        try:
            print("forkrun [WARN]: could not consume checkpoint "
                  "sidecar %r (%s); a later resume may re-deliver "
                  "these bytes" % (path, exc), file=sys.stderr)
        except Exception:
            pass
    return merged


__all__ = ["SIDECAR_SUFFIX", "WORKER_REAP_TIMEOUT",
           "ORDERER_REAP_TIMEOUT", "path_has_c_orderer",
           "require_resume_path", "resolve_checkpoint_dest",
           "resume_begin", "checkpoint_on_abort", "consume_sidecar"]
