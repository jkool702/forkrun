"""Python reactor: event-driven worker lifecycle management (W-PY19).

Translates the bash wrapper's ring_poll reactor loop into Python.
Manages worker spawning, death detection, respawn, trap-ACK
confirmation, and poison batch tracking.

The reactor runs in the PARENT process. For map/run it supervises
fork-and-wait to completion; for stream it supervises alongside the
drain loop (results yield while workers run).

Design mirrors the bash wrapper:
  - ring_poll → select on death pipes + spawn pipe + trap-ACK pipe
  - SPAWN event → fork new workers on the requested node
  - WORKER_DEATH → waitpid, classify, respawn if needed
  - TRAP_ACK → confirm graceful failure (worker trapped before death)
  - SCAN_DEATH → abort if the scanner failed
  - TIMEOUT → worker died without trap-ACK inside the grace (fatal)

OPT-IN: only used when run/map/stream are called with
orchestrator=True. Default paths never import this module's loop.

Death-pipe semantics: each worker holds the write end of its own
pipe; the parent holds the read end and closes its write copy at
fork. Any worker exit (clean, crash, SIGKILL) closes the last write
end, which the parent observes as readable EOF on the read end —
the kernel-observable mechanism (SIGKILL/OOM run no code, so traps
alone cannot be the detector). select() reports the EOF pipe as
readable; a zero-length read confirms the death.
"""

from __future__ import annotations

import os
import select as _select
import time as _time
from collections import defaultdict

# Trap-ACK grace: bash protocol constant (3s). A worker that exits
# non-zero must confirm via the trap-ACK pipe within this long, or
# the reactor declares catastrophic failure. Matches
# FR_TRAP_ACK_GRACE_MS_DEFAULT in forkrun_substrate.h.
TRAP_ACK_GRACE_S = 3.0

# Order-pipe capacity (bash H3 invariant: 1 page for backpressure).
ORDER_PIPE_SIZE = 4096


class WorkerSlot:
    """One worker's lifecycle state (bash: W_INCARN, P, W_NODE arrays)."""

    __slots__ = ('wid', 'node', 'pid', 'incarn', 'death_r', 'death_w',
                 'trap_ack_pending', 'alive')

    def __init__(self, wid, node, pid, death_r, death_w, incarn=0):
        self.wid = wid
        self.node = node
        self.pid = pid
        self.incarn = incarn
        self.death_r = death_r    # parent's read end of death pipe
        self.death_w = death_w    # closed in parent after fork (child owns)
        self.trap_ack_pending = 0  # >0 = death seen, waiting for ACK
        self.alive = True


class ReactorState:
    """Reactor-owned worker lifecycle state (bash: reactor locals).

    max_workers: hard cap on TOTAL workers ever serving this run
      (spawn requests beyond it are clamped, never rejected loudly).
    num_nodes: NUMA nodes served (v0 UMA: 1; node assignment is
      recorded per slot for lineage — multi-node rings are W-PY20).
    respawn_cap: max respawns per worker slot (-1 = unlimited).
      Mirrors fr_config_t.respawn_cap.
    spawn_ceiling: max LIVE workers (-1 = max_workers).
      Mirrors fr_config_t.spawn_ceiling.
    trap_ack_grace: seconds to wait for trap-ACK after a non-zero
      death before declaring catastrophic (default TRAP_ACK_GRACE_S).
    """

    def __init__(self, max_workers, num_nodes=1, respawn_cap=-1,
                 spawn_ceiling=-1, trap_ack_grace=TRAP_ACK_GRACE_S):
        self.workers = {}  # wid -> WorkerSlot
        self.max_workers = max_workers
        self.num_nodes = max(1, num_nodes)
        self.respawn_cap = respawn_cap
        self.spawn_ceiling = (spawn_ceiling if spawn_ceiling is not None
                              and spawn_ceiling >= 0 else max_workers)
        self.trap_ack_grace = trap_ack_grace
        self.node_workers = defaultdict(int)  # node -> live count
        self.node_worker_max = max(1, max_workers // self.num_nodes)

        # Free worker IDs (bash: wID_free array). Sized max + nodes so
        # a respawn never fails for want of an ID while slots are free.
        self.wid_free = set(range(max_workers + self.num_nodes))

        # Poisoned batch tracking (bash: POISONED_BATCHES).
        self.poisoned_batches = []

        # Trap-ACK timeout tracking: wid -> monotonic deadline.
        self.trap_ack_deadlines = {}

        # Spawn pipe (scanner -> parent). -1 disarms.
        self.spawn_r = -1

        # Trap-ACK pipe (workers -> parent). _r read here, _w lent out.
        self.trap_ack_r = -1
        self.trap_ack_w = -1
        self._trap_buf = b""
        self._spawn_buf = b""

        # Reaped exit statuses [(pid, status)] for the caller's
        # failure accounting (bash: wait-collected P array).
        self.statuses = []

        # Respawn accounting: bounded crash loops terminate via
        # respawn_cap, but the caller must still fail the run when
        # deaths were never recovered (cap reached with work lost).
        self.n_respawns = 0
        self.n_unrecovered = 0
        self.recovered = []  # wid list: unacked death later healed

        # Fork context for (re)spawn — set by configure(). Everything
        # a child needs is captured here so worker_died can respawn
        # without the caller re-supplying arguments.
        self.ctx = {}

    def configure(self, *, payload_spec, sink_spec, memfd, file_size,
                  out_fds, signal_w, fallow_w=-1, order_w=-1,
                  trap_ack_w=-1, on_error="retry", engine_fds=frozenset(),
                  splice=False):
        """Capture the fork context respawns need (parent-side)."""
        self.ctx = {
            "payload_spec": payload_spec,
            "sink_spec": sink_spec,
            "memfd": memfd,
            "file_size": file_size,
            "out_fds": out_fds,
            "signal_w": signal_w,
            "fallow_w": fallow_w,
            "order_w": order_w,
            "trap_ack_w": trap_ack_w,
            "on_error": on_error,
            "engine_fds": set(engine_fds),
            "splice": bool(splice),
        }
        if trap_ack_w is not None and trap_ack_w >= 0:
            self.trap_ack_w = trap_ack_w

    def live_count(self) -> int:
        """Currently alive workers."""
        return sum(1 for s in self.workers.values() if s.alive)

    def spawn_worker(self, wid=None, node=0):
        """Fork one worker with a death pipe. Returns WorkerSlot/None.

        wid None → lowest free ID. Returns None when no free slot
        exists (caller clamps, never raises). incarn continues the
        slot's lineage (0 for a fresh slot).
        """
        if wid is None:
            if not self.wid_free:
                return None
            wid = min(self.wid_free)
            self.wid_free.discard(wid)
        elif wid in self.workers and self.workers[wid].alive:
            return None  # slot occupied — never double-fork a live wid
        else:
            self.wid_free.discard(wid)

        ctx = self.ctx
        prev = self.workers.get(wid)
        incarn = (prev.incarn + 1) if prev is not None else 0

        try:
            death_r, death_w = os.pipe()
        except OSError:
            self.wid_free.add(wid)
            return None

        pid = os.fork()
        if pid == 0:
            # Child — never returns.
            try:
                os.close(death_r)
            except OSError:
                pass
            try:
                from ._fd_scrub import scrub_fds
                keep = set(ctx.get("engine_fds", ())) | {
                    ctx["memfd"], death_w}
                for key in ("signal_w", "fallow_w", "order_w",
                            "trap_ack_w"):
                    fd = ctx.get(key, -1)
                    if fd is not None and fd >= 0:
                        keep.add(fd)
                out_fds = ctx.get("out_fds") or []
                if out_fds and 0 <= wid < len(out_fds):
                    keep.add(out_fds[wid])
                scrub_fds(keep)
            except Exception:
                pass
            try:
                if ctx.get("splice"):
                    rc = _splice_child_main(
                        ctx, wid, node, incarn, death_w)
                else:
                    from ._worker import worker_main_with_death_pipe
                    out_fds = ctx.get("out_fds") or []
                    worker_main_with_death_pipe(
                        wid, node, ctx["payload_spec"],
                        ctx.get("sink_spec"), ctx["memfd"],
                        ctx["file_size"],
                        out_fds[wid] if out_fds and
                        0 <= wid < len(out_fds) else None,
                        ctx.get("signal_w"), death_r, death_w,
                        ctx.get("trap_ack_w", -1), ctx.get("on_error",
                                                           "retry"),
                        ctx.get("fallow_w", -1), ctx.get("order_w", -1),
                        incarn)
                    rc = 127  # unreachable; worker_main exits
            except BaseException:
                rc = 1
            os._exit(rc if isinstance(rc, int) and 0 <= rc < 256 else 1)

        # Parent: the write end belongs to the child now.
        try:
            os.close(death_w)
        except OSError:
            pass
        slot = WorkerSlot(wid, node, pid, death_r, -1, incarn=incarn)
        self.workers[wid] = slot
        self.node_workers[node] += 1
        return slot

    def worker_died(self, wid):
        """Reap one dead worker; respawn or free its slot.

        The caller must have PROOF of exit (death-pipe EOF): this
        waitpids blocking, which returns at once for a dead child.
        Returns ("respawned", new_slot) | ("clean", None) |
        ("pending", None). "pending" means a non-zero death whose
        trap-ACK grace is still running: the husk slot stays until
        the ACK arrives or the deadline fires (the reactor loop
        enforces it).
        """
        slot = self.workers.get(wid)
        if slot is None or not slot.alive:
            return ("clean", None)
        try:
            _, status = os.waitpid(slot.pid, 0)
        except ChildProcessError:
            status = 0  # already reaped elsewhere; treat as clean
        except OSError:
            status = 1
        return self._classify(slot, status)

    def note_exit(self, wid, status):
        """Classify an ALREADY-reaped exit (WNOHANG sweep); no waitpid.

        Same returns as worker_died. Used when the out-of-band sweep
        reaped the child first — the death pipe still gets drained by
        the main loop for ordering, but the status is already in hand.
        """
        slot = self.workers.get(wid)
        if slot is None or not slot.alive:
            return ("clean", None)
        return self._classify(slot, status)

    def _classify(self, slot, status):
        """Shared death handling: close pipe, bookkeep, respawn/free."""
        wid = slot.wid
        self.statuses.append((slot.pid, status))
        if slot.death_r is not None and slot.death_r >= 0:
            try:
                os.close(slot.death_r)
            except OSError:
                pass
            slot.death_r = -1
        slot.alive = False
        try:
            self.node_workers[slot.node] -= 1
        except KeyError:
            pass

        if os.WIFEXITED(status):
            exit_code = os.WEXITSTATUS(status)
        else:
            exit_code = 1  # signaled — a crash by definition

        if exit_code == 0:
            # A clean exit from a generation carrying an inherited
            # unacked death means the respawn drained to EOF: the
            # engine published everything consumable and this worker
            # consumed to the end, so the pipeline is whole — heal
            # the pending grace instead of orphaning it into a false
            # catastrophic at termination.
            if slot.trap_ack_pending > 0:
                slot.trap_ack_pending = 0
                self.trap_ack_deadlines.pop(wid, None)
                self.recovered.append(wid)
            elif slot.trap_ack_pending < 0:
                # Defensive: transient credit should always have been
                # consumed by the death that preceded this clean exit
                # (respawn is synchronous with death observation).
                # Normalize rather than carry a stale balance.
                slot.trap_ack_pending = 0
                self.trap_ack_deadlines.pop(wid, None)
            self.wid_free.add(wid)
            del self.workers[wid]
            return ("clean", None)

        # Non-zero death: trap-ACK bookkeeping (bash pending logic).
        # Deaths and ACKs pipeline in EITHER order (an ACK can sit in
        # the pipe before the death-pipe EOF is selected), so this is
        # a SIGNED counter, not a flag: each death +1, each ACK -1,
        # and the grace lives only while the balance is positive. A
        # death/death/ack/ack sequence balances (1,2 → 1,0); an
        # ack-before-death leaves transient credit (-1) that the
        # death consumes back to 0 instead of orphaning a grace into
        # a false catastrophic.
        slot.trap_ack_pending += 1
        if slot.trap_ack_pending > 0 and \
                wid not in self.trap_ack_deadlines:
            self.trap_ack_deadlines[wid] = (
                _time.monotonic() + self.trap_ack_grace)

        # Bounded respawn (bash: respawn on the same node).
        cap = self.respawn_cap
        if cap is not None and cap >= 0 and slot.incarn >= cap:
            self.n_unrecovered += 1
            return ("pending", None)  # cap reached: wait grace, no respawn
        new_slot = self.spawn_worker(wid=wid, node=slot.node)
        if new_slot is None:
            self.n_unrecovered += 1
            return ("pending", None)
        self.n_respawns += 1
        # The new generation inherits the pending ACK wait: the ACK
        # names the wid, not the generation.
        new_slot.trap_ack_pending = slot.trap_ack_pending
        return ("respawned", new_slot)

    def check_trap_timeouts(self):
        """Raise RuntimeError for any expired trap-ACK grace."""
        now = _time.monotonic()
        for wid, deadline in list(self.trap_ack_deadlines.items()):
            if now >= deadline:
                slot = self.workers.get(wid)
                pending = slot.trap_ack_pending if slot else 1
                if pending > 0:
                    raise RuntimeError(
                        "forkrun: Worker %d exited non-zero and trap-ACK "
                        "did not confirm within %.0fs. Aborting."
                        % (wid, self.trap_ack_grace))
                self.trap_ack_deadlines.pop(wid, None)

    def reap_clean_exits(self):
        """WNOHANG sweep for exits the death pipe hasn't flagged yet.

        The death pipe is the primary detector; this catches exits
        observed out-of-band. Reaped exits are classified immediately
        (respawn included) via note_exit — never blocks.
        """
        for wid, slot in list(self.workers.items()):
            if not slot.alive:
                continue
            try:
                wpid, status = os.waitpid(slot.pid, os.WNOHANG)
            except ChildProcessError:
                continue  # reaped elsewhere; pipe EOF confirms below
            except OSError:
                continue
            if wpid == slot.pid:
                self.note_exit(wid, status)


def _splice_child_main(ctx, wid, node, incarn, death_w):
    """C-loop passthrough worker with death-pipe + trap-ACK (W-PY19).

    Runs in the forked child. Returns the exit code for os._exit.
    """
    from ._bindings import get as _get
    lib = _get()
    trap_w = ctx.get("trap_ack_w", -1)
    try:
        if lib.fr_py_worker_init(wid, node, incarn, 3, 0) != 0:
            return 1
        order_w = ctx.get("order_w", -1)
        if order_w is not None and order_w >= 0:
            try:
                lib.fr_py_set_order_pipe(order_w)
            except Exception:
                pass
        out_fds = ctx.get("out_fds") or []
        out_fd = (out_fds[wid] if out_fds and 0 <= wid < len(out_fds)
                  else -1)
        sig_w = ctx.get("signal_w", -1)
        sig = sig_w if sig_w is not None and sig_w >= 0 else -1
        fal_w = ctx.get("fallow_w", -1)
        fal = fal_w if fal_w is not None and fal_w >= 0 else -1
        rc = lib.fr_py_worker_splice_loop(
            wid, ctx["memfd"], out_fd, sig, fal)
    except BaseException:
        rc = 1
    if rc != 0:
        try:
            lib.fr_py_escrow_deposit(1)
        except Exception:
            pass
        if trap_w is not None and trap_w >= 0:
            try:
                os.write(trap_w, ("%d\n" % (wid,)).encode())
            except OSError:
                pass
    try:
        os.close(death_w)
    except OSError:
        pass
    return 0 if rc == 0 else 1


def handle_trap_ack_bytes(state, data):
    """Consume raw trap-ACK pipe bytes into reactor state.

    Lines: "wid" (graceful-failure confirmation) or "P:idx:kills"
    (poison notification, bash TRAP_ACK-event poison arm).
    """
    if not data:
        return
    state._trap_buf += data
    while b"\n" in state._trap_buf:
        line, state._trap_buf = state._trap_buf.split(b"\n", 1)
        line = line.decode("utf-8", errors="replace").strip()
        if not line:
            continue
        if line.startswith("P:"):
            parts = line[2:].split(":")
            if len(parts) == 2:
                state.poisoned_batches.append(
                    "Index %s (failed %s times)" % (parts[0], parts[1]))
            continue
        try:
            wid = int(line)
        except ValueError:
            continue
        slot = state.workers.get(wid)
        if slot is not None:
            # Signed balance (see _classify): an ACK arriving before
            # its death is observed leaves credit (negative) that the
            # death consumes back toward zero — never clamped here.
            # The grace lives only while the balance is positive.
            slot.trap_ack_pending -= 1
            if slot.trap_ack_pending <= 0:
                state.trap_ack_deadlines.pop(wid, None)


def handle_spawn_bytes(state, data):
    """Consume raw scanner spawn-pipe bytes; fork workers per line.

    Lines: "count" (UMA) or "node:count" (NUMA). Clamped to the
    max_workers hard cap and the per-node max — never raises for
    malformed lines (a babbling scanner must not kill the run; the
    engine's own accounting already added the request to W).
    """
    if not data:
        return
    state._spawn_buf += data
    while b"\n" in state._spawn_buf:
        line, state._spawn_buf = state._spawn_buf.split(b"\n", 1)
        line = line.decode("utf-8", errors="replace").strip()
        if not line:
            continue
        try:
            if ":" in line:
                node_s, count_s = line.split(":", 1)
                node, count = int(node_s), int(count_s)
            else:
                node, count = 0, int(line)
        except ValueError:
            continue
        if count <= 0:
            continue
        if node < 0 or node >= state.num_nodes:
            node = 0
        live = state.live_count()
        if live + count > state.spawn_ceiling:
            count = state.spawn_ceiling - live
        node_cur = state.node_workers.get(node, 0)
        if node_cur + count > state.node_worker_max:
            count = state.node_worker_max - node_cur
        for _ in range(max(0, count)):
            if state.spawn_worker(node=node) is None:
                break


def reactor_loop(state, drain_gen=None, poll_timeout=0.1):
    """Supervise workers to completion (bash ring_poll equivalent).

    Death pipes + spawn pipe + trap-ACK pipe are select()ed each
    round; expirations raise RuntimeError (catastrophic: death
    without trap-ACK inside the grace). drain_gen (optional) is a
    zero-arg callable returning the next result blob, None when no
    complete record is available YET (not EOF — the loop keeps
    polling), or raising StopIteration when the stream is exhausted:
    while any worker is alive the loop pumps it and YIELDS each blob
    (streaming mode); when drain_gen is None the loop only
    supervises (map/run mode).

    Yields result blobs (streaming) and returns
    {"statuses": [(pid, status)], "poisoned": [...]}.
    Raises RuntimeError on trap-ACK timeout. Never returns while a
    worker is alive.
    """

    def _drain_pipe_nonblock(fd, buf_attr):
        try:
            chunk = os.read(fd, 4096)
        except BlockingIOError:
            return b""
        except OSError:
            return None
        if chunk == b"":
            return None  # EOF: writers all gone
        return chunk

    while True:
        # 1. Catastrophic check first (a dead grace aborts even when
        #    fresh work is arriving).
        state.check_trap_timeouts()

        # 2. Death-pipe + spawn + trap-ACK events.
        watch = []
        death_of = {}
        for slot in state.workers.values():
            if slot.alive and slot.death_r is not None \
                    and slot.death_r >= 0:
                watch.append(slot.death_r)
                death_of[slot.death_r] = slot.wid
        if state.spawn_r is not None and state.spawn_r >= 0:
            watch.append(state.spawn_r)
        if state.trap_ack_r is not None and state.trap_ack_r >= 0:
            watch.append(state.trap_ack_r)

        if watch:
            try:
                readable, _, _ = _select.select(watch, [], [],
                                                poll_timeout)
            except (OSError, ValueError):
                readable = []
            for fd in readable:
                if fd == state.spawn_r:
                    chunk = _drain_pipe_nonblock(fd, "_spawn_buf")
                    if chunk is None:
                        try:
                            os.close(state.spawn_r)
                        except OSError:
                            pass
                        state.spawn_r = -1
                    elif chunk:
                        handle_spawn_bytes(state, chunk)
                elif fd == state.trap_ack_r:
                    chunk = _drain_pipe_nonblock(fd, "_trap_buf")
                    if chunk is None:
                        try:
                            os.close(state.trap_ack_r)
                        except OSError:
                            pass
                        state.trap_ack_r = -1
                    elif chunk:
                        handle_trap_ack_bytes(state, chunk)
                else:
                    wid = death_of.get(fd)
                    if wid is None:
                        continue
                    # Readable death pipe: consume to EOF. Any bytes
                    # (none are ever written — the pipe is purely a
                    # kernel-observable lifetime channel) or EOF both
                    # mean the worker is gone; worker_died reaps it.
                    try:
                        os.read(fd, 4096)
                    except OSError:
                        pass
                    kind, _new = state.worker_died(wid)
                    _slot = state.workers.get(wid)
                    if _slot is not None and not _slot.alive:
                        # Respawn failed or cap reached with no live
                        # generation: free the husk so termination can
                        # be observed (the grace deadline still fires
                        # for the missing ACK via check_trap_timeouts).
                        pass
        else:
            _time.sleep(poll_timeout)

        # 3. Out-of-band exit sweep (covers exits whose pipe EOF the
        #    select above hasn't observed yet this round; non-blocking,
        #    classifies + respawns inline).
        state.reap_clean_exits()

        # 4. Streaming drain pump (None = nothing complete YET,
        #    keep polling; StopIteration = stream exhausted for good).
        if drain_gen is not None:
            try:
                blob = drain_gen()
            except StopIteration:
                drain_gen = None
            else:
                if blob is not None:
                    yield blob
                # After yielding (or an empty quantum), re-check
                # timeouts promptly rather than sleeping a full
                # quantum with a dead grace.
                state.check_trap_timeouts()

        # 5. Termination: no live worker AND (no drain pending or the
        #    drain is exhausted). Deaths with a running grace keep
        #    their husk slots (alive False) — but termination must
        #    not wait out a grace when no generation remains to ACK:
        #    check_trap_timeouts at the top of the next round raises
        #    if the grace is truly orphaned, so reaching here with no
        #    live worker and an exhausted drain means done.
        live = [s for s in state.workers.values() if s.alive]
        if not live and (drain_gen is None):
            if state.trap_ack_deadlines:
                # Graces still running with no live workers left: an
                # ACK may still be buffered in the trap pipe (the
                # dying generation's finally wrote before exit), so
                # poll once more instead of breaking. Expiry raises
                # from check_trap_timeouts at the top of the next
                # round (catastrophic: death without confirmation).
                # A husk-only wait always terminates: every deadline
                # either clears (buffered ACK) or fires (~3s).
                if state.trap_ack_r is not None \
                        and state.trap_ack_r >= 0:
                    try:
                        _r, _, _ = _select.select(
                            [state.trap_ack_r], [], [], poll_timeout)
                    except (OSError, ValueError):
                        _r = []
                    if state.trap_ack_r in _r:
                        try:
                            _chunk = os.read(state.trap_ack_r, 4096)
                        except OSError:
                            _chunk = b""
                        if _chunk:
                            handle_trap_ack_bytes(state, _chunk)
                else:
                    _time.sleep(poll_timeout)
                continue
            break

    return {"statuses": list(state.statuses),
            "poisoned": list(state.poisoned_batches)}


def reactor_run(state, poll_timeout=0.1):
    """Blocking supervision (map/run): exhaust reactor_loop, return its
    result dict. Raises RuntimeError on trap-ACK timeout."""
    gen = reactor_loop(state, None, poll_timeout)
    try:
        while True:
            next(gen)
    except StopIteration as _stop:
        if isinstance(_stop.value, dict):
            return _stop.value
    return {"statuses": list(state.statuses),
            "poisoned": list(state.poisoned_batches)}


def reactor_poll_once(state, poll_timeout=0.0):
    """Service one nonblocking event round (spill-loop interleaving).

    Runs a single select round over death/spawn/trap-ACK pipes plus
    the timeout check and the out-of-band reap sweep. Used by
    blocking ingest paths that must supervise workers WHILE spilling
    synchronously (they cannot enter reactor_run until the spill and
    gate are done). Never blocks beyond poll_timeout (0 = pure poll).
    Raises RuntimeError on trap-ACK timeout.
    """
    state.check_trap_timeouts()
    watch = []
    death_of = {}
    for slot in state.workers.values():
        if slot.alive and slot.death_r is not None and slot.death_r >= 0:
            watch.append(slot.death_r)
            death_of[slot.death_r] = slot.wid
    if state.spawn_r is not None and state.spawn_r >= 0:
        watch.append(state.spawn_r)
    if state.trap_ack_r is not None and state.trap_ack_r >= 0:
        watch.append(state.trap_ack_r)
    if watch:
        try:
            readable, _, _ = _select.select(watch, [], [], poll_timeout)
        except (OSError, ValueError):
            readable = []
        for fd in readable:
            if fd == state.spawn_r:
                try:
                    chunk = os.read(fd, 4096)
                except OSError:
                    continue
                if chunk:
                    handle_spawn_bytes(state, chunk)
            elif fd == state.trap_ack_r:
                try:
                    chunk = os.read(fd, 4096)
                except OSError:
                    continue
                if chunk:
                    handle_trap_ack_bytes(state, chunk)
            else:
                wid = death_of.get(fd)
                if wid is None:
                    continue
                try:
                    os.read(fd, 4096)
                except OSError:
                    pass
                state.worker_died(wid)
    state.reap_clean_exits()
    state.check_trap_timeouts()


def report_poisoned(poisoned) -> None:
    """Stderr poison summary (bash POISONED_BATCHES equivalent)."""
    if not poisoned:
        return
    import sys as _sys
    _sys.stderr.write(
        "\n=================================================================\n"
        "forkrun [ERROR]: POISONED BATCH SUMMARY\n"
        "=================================================================\n"
        "The pipeline completed, but %d batch(es) failed repeatedly\n"
        "and were permanently skipped:\n" % len(poisoned))
    for b in poisoned:
        _sys.stderr.write("  - Batch %s\n" % (b,))
    _sys.stderr.write(
        "=================================================================\n")


def spawn_orderer(order_r, output_fd=1, unordered=False, numa=False,
                  engine_fds=frozenset(), out_fds=()):
    """Fork the C orderer (bash ring_order subshell equivalent).

    order_r: read end of the order pipe (workers ack OrderPackets to
      the write end). output_fd: collection fd the ordered bytes go
      to (dup2'd to stdout in the child). out_fds: the workers'
      output memfds — the orderer reads payload bytes from them via
      the OrderPackets' (fd, off, len), so they MUST stay open here
      (scrub keeps them). Returns the child pid; the child scrubs to
      {order_r, output_fd} + out_fds + engine fds and never returns
      (os._exit with the engine rc).
    """
    from ._bindings import get as _get
    lib = _get()
    pid = os.fork()
    if pid == 0:
        try:
            from ._fd_scrub import scrub_fds
            keep = set(engine_fds) | {order_r, output_fd}
            for _fd in out_fds:
                if _fd is not None and _fd >= 0:
                    keep.add(_fd)
            scrub_fds(keep)
        except Exception:
            pass
        try:
            rc = lib.fr_py_orderer(order_r, output_fd,
                                   1 if unordered else 0,
                                   1 if numa else 0)
        except BaseException:
            rc = 1
        os._exit(rc if isinstance(rc, int) and 0 <= rc < 256 else 1)
    return pid


def fork_scanner_with_death_pipe(lib, memfd, spawn_w=-1,
                                 engine_fds=frozenset()):
    """Fork the scanner with a death pipe (bash SCAN_DEATH equivalent).

    Returns (pid, death_r). The parent holds death_r and closes its
    write copy at once; scanner exit (any cause) reads as EOF. When
    spawn_w >= 0 the scanner forwards spawn requests there (dynamic
    scaling); -1 runs the plain scan.
    """
    death_r, death_w = os.pipe()
    pid = os.fork()
    if pid == 0:
        try:
            os.close(death_r)
        except OSError:
            pass
        try:
            from ._fd_scrub import scrub_fds
            keep = set(engine_fds) | {memfd, death_w}
            if spawn_w is not None and spawn_w >= 0:
                keep.add(spawn_w)
            scrub_fds(keep)
        except Exception:
            pass
        try:
            if spawn_w is not None and spawn_w >= 0:
                rc = lib.fr_py_scan_with_spawn(memfd, spawn_w)
            else:
                rc = lib.fr_py_scan(memfd)
        except BaseException:
            rc = 1
        os._exit(rc if isinstance(rc, int) and 0 <= rc < 256 else 1)
    try:
        os.close(death_w)
    except OSError:
        pass
    return pid, death_r


def check_scanner_death(scan_pid, death_r):
    """Classify scanner state: (status, exit_code).

    Returns ("running", None) while alive, ("clean", 0) on clean
    exit, ("error", code) on failure. Consumes (closes) death_r on a
    definitive answer. Never raises.
    """
    try:
        readable, _, _ = _select.select([death_r], [], [], 0)
    except (OSError, ValueError):
        return ("running", None)
    if death_r not in readable:
        # Confirm liveness out-of-band (pipe quiet but child gone?).
        try:
            wpid, status = os.waitpid(scan_pid, os.WNOHANG)
        except ChildProcessError:
            return ("clean", 0)
        except OSError:
            return ("running", None)
        if wpid != scan_pid:
            return ("running", None)
        code = os.WEXITSTATUS(status) if os.WIFEXITED(status) else 1
        try:
            os.close(death_r)
        except OSError:
            pass
        return ("clean", 0) if code == 0 else ("error", code)
    # Pipe signaled: drain to EOF then reap.
    try:
        while os.read(death_r, 4096) != b"":
            pass
    except OSError:
        pass
    try:
        os.close(death_r)
    except OSError:
        pass
    try:
        _, status = os.waitpid(scan_pid, 0)
    except ChildProcessError:
        return ("clean", 0)
    except OSError:
        return ("error", 1)
    code = os.WEXITSTATUS(status) if os.WIFEXITED(status) else 1
    return ("clean", 0) if code == 0 else ("error", code)


__all__ = ["WorkerSlot", "ReactorState", "reactor_loop", "reactor_run",
           "reactor_poll_once",
           "handle_trap_ack_bytes", "handle_spawn_bytes",
           "report_poisoned", "spawn_orderer",
           "fork_scanner_with_death_pipe", "check_scanner_death",
           "TRAP_ACK_GRACE_S", "ORDER_PIPE_SIZE"]
