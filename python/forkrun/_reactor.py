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

OPT-IN... no longer: since W-REL1/R1 the reactor is the DEFAULT
(run/map/stream with orchestrator=None ride this module's loop);
orchestrator=False selects legacy fork-and-wait fail-fast, which
never imports this module. Default paths DO import this loop.

Death-pipe semantics: each worker holds the write end of its own
pipe; the parent holds the read end and closes its write copy at
fork. Any worker exit (clean, crash, SIGKILL) closes the last write
end, which the parent observes as readable EOF on the read end —
the kernel-observable mechanism (SIGKILL/OOM run no code, so traps
alone cannot be the detector). select() reports the EOF pipe as
readable; a zero-length read confirms the death. The one pre-EOF
byte with meaning is READY_BYTE (W-REL6-3.1): the child writes it
once startup completes (payload resolved, worker_init done), and
the parent's per-worker startup deadline SIGKILLs children that
never send it (fork-from-threaded-host hangs become bounded
recovery instead of a silent select() wait).
"""

from __future__ import annotations

import os
import select as _select
import signal as _signal
import time as _time
from collections import defaultdict

# Trap-ACK grace: bash protocol constant (3s). A worker that exits
# non-zero must confirm via the trap-ACK pipe within this long, or
# the reactor declares catastrophic failure. Matches
# FR_TRAP_ACK_GRACE_MS_DEFAULT in forkrun_substrate.h.
TRAP_ACK_GRACE_S = 3.0

# W-REL5-B5: bounded death-confirm spin for worker_died_poll.
# Death-pipe EOF precedes os._exit, so a descheduled child is
# briefly unreaped while its pipe already signals death. The poll
# twin spins this long (then defers to the reap sweep) instead of
# blocking like worker_died.
DEATH_CONFIRM_SPIN_S = 0.5

# W-REL5-C9: SIGKILL/OOM-class respawn backoff bounds (jittered).
# Immediate respawn burns all generations in ~0.01s when every new
# worker is SIGKILLed at birth (OOM pressure, kill -9 loops) —
# aborting runs a short delay survives. Deterministic crashes
# (plain exit != 0, other signals) keep immediate respawn: the
# batch-level escrow/retry/poison path already converges those
# fast, and delaying them only postpones the abort.
RESPAWN_SIGKILL_BACKOFF_MIN_S = 0.05
RESPAWN_SIGKILL_BACKOFF_MAX_S = 0.2

# Per-round drain burst cap (see reactor_loop §4).
DRAIN_BURST = 64
# W-PYREAPSWEEP: minimum interval between the out-of-band reap backstop
# sweeps. The death pipe is the primary death detector and is in the
# reactor's watch set, so this only bounds how long an UNFLAGGED exit
# can go unnoticed; teardown reaps definitively regardless.
#
# Kept small deliberately: the sweep is N waitpid syscalls, so the win
# is in the COUNT, not the interval. At 2ms a 79k-batch run does ~150
# sweeps instead of 79500 -- a ~500x cut -- while the worst-case
# end-of-run latency stays inside measurement noise. A 20ms version
# cost stream() ~6% purely in wind-down latency.
_REAP_SWEEP_INTERVAL_S = 0.002

# W-REL6-3.1: per-worker startup deadline. A child forked from a
# threaded host can deadlock before signaling readiness (frozen
# post-fork import); the reactor select()s forever on its silent
# death pipe. Any reactor child that has not written READY_BYTE
# within this long is SIGKILLed and treated as a death (the normal
# recovery path respawns it). Generous default: healthy startup is
# milliseconds; only a hung child ever observes this. Override with
# FORKRUN_WORKER_STARTUP_S (tests use sub-second values).
STARTUP_DEADLINE_S = 30.0
STARTUP_DEADLINE_ENV = "FORKRUN_WORKER_STARTUP_S"

# Order-pipe capacity (bash H3 invariant: 1 page for backpressure).
ORDER_PIPE_SIZE = 4096


def _death_cause(status):
    """Worker-death cause from a waitpid status (D-PORT3).

    Returns (exit_code, signo_or_None). Signal deaths map to the
    shell 128+signo convention (Bash 130/143 reachable) instead of
    collapsing to 1: the C recovery core only branches on ==0, so
    recovery behavior is unchanged while the reactor keeps the true
    cause for taxonomy errors and forensics.
    """
    if os.WIFEXITED(status):
        return os.WEXITSTATUS(status), None
    if os.WIFSIGNALED(status):
        _sig = os.WTERMSIG(status)
        return 128 + _sig, _sig
    return 1, None  # stopped/continued: generic crash


class WorkerSlot:
    """One worker's lifecycle state (bash: W_INCARN, P, W_NODE arrays)."""

    __slots__ = ('wid', 'node', 'pid', 'incarn', 'death_r', 'death_w',
                 'trap_ack_pending', 'alive', 'ready', 'spawned_at')

    def __init__(self, wid, node, pid, death_r, death_w, incarn=0):
        self.wid = wid
        self.node = node
        self.pid = pid
        self.incarn = incarn
        self.death_r = death_r    # parent's read end of death pipe
        self.death_w = death_w    # closed in parent after fork (child owns)
        self.trap_ack_pending = 0  # >0 = death seen, waiting for ACK
        self.alive = True
        # W-REL6-3.1: startup handshake. ready flips when the child
        # writes READY_BYTE on the death pipe (setup complete); the
        # startup deadline runs from spawned_at (fork moment).
        self.ready = False
        self.spawned_at = _time.monotonic()


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
    startup_deadline: seconds a forked worker may take to signal
      readiness (READY_BYTE) before it is SIGKILLed and treated as
      a death (W-REL6-3.1). None resolves via
      FORKRUN_WORKER_STARTUP_S, else STARTUP_DEADLINE_S.
    """

    def __init__(self, max_workers, num_nodes=1, respawn_cap=-1,
                 spawn_ceiling=-1, trap_ack_grace=TRAP_ACK_GRACE_S,
                 startup_deadline=None, wid_node=None):
        self.workers = {}  # wid -> WorkerSlot
        # W-PYSPAWNWIRE: stable wid -> node assignment, mirroring the
        # orchestrator's wid_to_node(). The scanner's spawn requests name
        # a node, so the wid chosen for one MUST belong to that node's
        # block; picking min(wid_free) regardless would put a worker in a
        # ring that disagrees with wid_node, which is the mapping the
        # NUMA drain audit verifies against (it reported a covered node
        # with published-but-unclaimed batches). None means UMA, where
        # every wid is node 0 and the default is already correct.
        self.wid_node = list(wid_node) if wid_node else None
        # W-PYREAPSWEEP: last out-of-band reap backstop sweep (monotonic).
        self._reap_last = 0.0
        self.max_workers = max_workers
        self.num_nodes = max(1, num_nodes)
        self.respawn_cap = respawn_cap
        self.spawn_ceiling = (spawn_ceiling if spawn_ceiling is not None
                              and spawn_ceiling >= 0 else max_workers)
        self.trap_ack_grace = trap_ack_grace
        if startup_deadline is None:
            try:
                startup_deadline = float(
                    os.environ.get(STARTUP_DEADLINE_ENV, ""))
            except (TypeError, ValueError):
                startup_deadline = STARTUP_DEADLINE_S
            if not startup_deadline or startup_deadline <= 0:
                startup_deadline = STARTUP_DEADLINE_S
        self.startup_deadline = startup_deadline
        # wid list: workers SIGKILLed by the startup deadline
        # (observability for tests/forensics; recovery proceeds
        # through the normal death path).
        self.startup_kills = []
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
                   splice=False, node_cpus=None, plugin_loop=None,
                   spawn_loop=None):
        """Capture the fork context respawns need (parent-side).

        plugin_loop (W-PY26): None (Python worker) or a (path, func)
        frozen-ABI pair — workers then run fr_py_worker_plugin_loop
        (zero Python per batch) instead of worker_main.
        spawn_loop (W-PY33): None (Python worker) or an argv list —
        workers then run fr_py_worker_spawn_loop (zero Python per
        batch) instead of worker_main. Mutually exclusive with
        plugin_loop/splice (the caller gates the envelope).

        W-REL6-3.1: string payload/sink specs are resolved HERE, in
        the parent, before any fork (backstop: the primary path is
        _coerce_payload at the public-API entry; resolving a callable
        is a no-op, so direct configure() callers with strings are
        covered too). Nothing reaching spawn_worker is ever imported
        post-fork.
        """
        from ._worker import resolve_payload_parent as _resolve_parent
        if payload_spec is not None:
            payload_spec = _resolve_parent(payload_spec)
        if sink_spec is not None:
            sink_spec = _resolve_parent(sink_spec)
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
            "plugin_loop": plugin_loop,
            "spawn_loop": (tuple(spawn_loop)
                           if spawn_loop is not None else None),
            "node_cpus": (list(node_cpus) if node_cpus is not None
                          else None),
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
            # W-PY21: best-effort pre-pinning to the worker's node
            # (fr_py_worker_init re-pins authoritatively via the
            # engine's logical→physical map right after; this only
            # narrows the pre-init window. Never fatal).
            try:
                _ncpus = ctx.get("node_cpus")
                if _ncpus and 0 <= node < len(_ncpus):
                    from ._numa import pin_to_node as _pin
                    _pin(_ncpus[node])
            except Exception:
                pass
            try:
                if ctx.get("splice"):
                    rc = _splice_child_main(
                        ctx, wid, node, incarn, death_w)
                elif ctx.get("plugin_loop"):
                    rc = _c_plugin_child_main(
                        ctx, wid, node, incarn, death_w)
                elif ctx.get("spawn_loop"):
                    rc = _c_spawn_child_main(
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
        Poll loops must use worker_died_poll instead (W-REL5-B5:
        EOF precedes os._exit, so this blocks on a descheduled
        child).
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

    def worker_died_poll(self, wid):
        """Non-blocking twin of worker_died (W-REL5-B5).

        WNOHANG reap; a live-but-EOF-signaled child (death-pipe
        EOF precedes os._exit — a descheduled child is briefly
        unreaped while already dead) spins bounded
        (DEATH_CONFIRM_SPIN_S), then defers as ("deferred", None)
        with the slot untouched (still alive, pipe open): the
        out-of-band reap_clean_exits sweep classifies it on a
        later round (the pipe stays EOF-readable, so no event is
        lost). Returns worker_died's ("respawned" | "clean" |
        "pending", ...) when the child reaped, ("deferred", None)
        otherwise, ("clean", None) for unknown/dead slots (same
        as worker_died). Never blocks beyond the spin — use this
        (not worker_died) from every poll loop.
        """
        slot = self.workers.get(wid)
        if slot is None or not slot.alive:
            return ("clean", None)
        deadline = _time.monotonic() + DEATH_CONFIRM_SPIN_S
        while True:
            try:
                wpid, status = os.waitpid(slot.pid, os.WNOHANG)
            except ChildProcessError:
                status = 0  # already reaped elsewhere; treat as clean
                break
            except OSError:
                status = 1
                break
            if wpid == slot.pid:
                break
            if _time.monotonic() >= deadline:
                return ("deferred", None)
            _time.sleep(0.005)
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

        # D-PORT3: signaled deaths ride the shell 128+signo
        # convention (not a flat 1) — recovery-safe (the C core
        # branches on ==0 only) and cause-faithful.
        exit_code, exit_signo = _death_cause(status)

        # W-PY29: universal parent-side recovery for ALL deaths,
        # INCLUDING exit 0. The C state machine
        # (ring_recover_worker_core) is the sole classification
        # authority: IDLE + exit 0 → NORMAL_EXIT (free, same outcome
        # as the old fast path); CLAIMED + exit 0 → FATAL (worker
        # bug — a correct worker only exits 0 at EOF with TXN_IDLE).
        #
        # Pre-W-PY28 substrates lack the symbol: fall back to the
        # legacy behavior verbatim (exit-0 fast path + trap-ACK grace
        # for non-zero; mixed-version safety).
        from ._bindings import get as _get
        _recover = getattr(_get(), "fr_py_recover_worker", None)
        if _recover is not None:
            _out_fds = (self.ctx.get("out_fds") or [])
            _out_fd = (_out_fds[wid]
                       if 0 <= wid < len(_out_fds) else -1)
            if _out_fd is None or _out_fd < 0:
                _out_fd = -1
            try:
                _rrc = _recover(wid, slot.incarn, _out_fd, exit_code)
            except Exception:
                _rrc = 5
            if _rrc == 2:
                # NORMAL_EXIT: the dead generation held no unacked
                # work (EOF drain or between-batch death at rest).
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
            if _rrc == 4:
                raise RuntimeError(
                    "forkrun: Worker %d died in the claim-without-"
                    "publish race%s; batch unattributable. Aborting."
                    % (wid, (" (signal %d)" % exit_signo)
                       if exit_signo is not None else ""))
            if _rrc == 5:
                raise RuntimeError(
                    "forkrun: Worker %d recovery failed "
                    "(orphan revert/escrow%s). Aborting."
                    % (wid, ("; death signal %d" % exit_signo)
                       if exit_signo is not None else ""))
            # rc 0 (RECOVERED) / 1 (NO_BATCH) / 3 (ALREADY_DONE):
            # the death is accounted for — proceed to the respawn tail
            # like a confirmed death. (rc 2 with a non-zero exit still
            # frees: the EOF teardown error holds no work.)
            # Only genuine orphan recoveries join the healed list.
            if _rrc == 0:
                self.recovered.append(wid)
        else:
            if exit_code == 0:
                if slot.trap_ack_pending > 0:
                    slot.trap_ack_pending = 0
                    self.trap_ack_deadlines.pop(wid, None)
                    self.recovered.append(wid)
                elif slot.trap_ack_pending < 0:
                    slot.trap_ack_pending = 0
                    self.trap_ack_deadlines.pop(wid, None)
                self.wid_free.add(wid)
                del self.workers[wid]
                return ("clean", None)

            # Legacy path: trap-ACK bookkeeping (bash pending logic).
            # Deaths and ACKs pipeline in EITHER order (an ACK can sit
            # in the pipe before the death-pipe EOF is selected), so
            # this is a SIGNED counter, not a flag: each death +1,
            # each ACK -1, and the grace lives only while the balance
            # is positive.
            slot.trap_ack_pending += 1
            if slot.trap_ack_pending > 0 and \
                    wid not in self.trap_ack_deadlines:
                self.trap_ack_deadlines[wid] = (
                    _time.monotonic() + self.trap_ack_grace)

        # Bounded respawn (bash: respawn on the same node).
        cap = self.respawn_cap
        if cap is not None and cap >= 0 and slot.incarn >= cap:
            self.n_unrecovered += 1
            return ("pending", None)  # cap reached: no respawn
        if exit_signo == 9:  # SIGKILL: OOM-class/environmental death
            # W-REL5-C9: jittered backoff before respawning (cap
            # already enforced above, so a persistent killer still
            # terminates via ("pending", None) — just slower, giving
            # transient pressure a chance to clear). Other deaths
            # respawn immediately (deterministic crashes converge
            # via escrow/poison without delay).
            import random as _random  # noqa: PLC0415

            _time.sleep(_random.uniform(
                RESPAWN_SIGKILL_BACKOFF_MIN_S,
                RESPAWN_SIGKILL_BACKOFF_MAX_S))
        new_slot = self.spawn_worker(wid=wid, node=slot.node)
        if new_slot is None:
            self.n_unrecovered += 1
            return ("pending", None)
        self.n_respawns += 1
        # The new generation inherits the pending ACK wait: the ACK
        # names the wid, not the generation. (Always 0 on the W-PY28
        # path — no grace is ever armed there.)
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

    def note_ready(self, wid, data):
        """Consume death-pipe bytes for a live worker (W-REL6-3.1).

        Returns True when the bytes were the readiness signal (caller
        must NOT treat the pipe as dead), False on EOF (caller runs
        the normal death path). The pipe is otherwise write-silent,
        so any pre-EOF byte marks the worker ready; stray bytes on
        an already-ready worker are consumed and ignored (never a
        death -- the kernel still reports the true exit as EOF).
        """
        slot = self.workers.get(wid)
        if slot is None or not slot.alive:
            return False
        if not data:
            return False  # EOF: dead
        from ._worker import READY_BYTE as _READY
        if not slot.ready and data[:1] == _READY:
            slot.ready = True
        return True

    def check_startup_timeouts(self):
        """SIGKILL workers that never signaled readiness (W-REL6-3.1).

        A child forked from a threaded host can deadlock before setup
        completes (no READY_BYTE, no exit -- the death pipe stays
        silent and select() would wait forever). Expired workers are
        SIGKILLed here; the resulting death flows through the normal
        reap/respawn path (bounded by respawn_cap), so a hung
        generation becomes bounded recovery instead of a hang. Never
        raises; records kills in startup_kills for observability.
        """
        now = _time.monotonic()
        for wid, slot in list(self.workers.items()):
            if not slot.alive or slot.ready:
                continue
            if now - slot.spawned_at < self.startup_deadline:
                continue
            try:
                os.kill(slot.pid, _signal.SIGKILL)
            except OSError:
                pass
            else:
                self.startup_kills.append(wid)

    def reap_clean_exits(self, force=False):
        """WNOHANG sweep for exits the death pipe hasn't flagged yet.

        The death pipe is the primary detector; this catches exits
        observed out-of-band. Reaped exits are classified immediately
        (respawn included) via note_exit — never blocks.

        W-PYREAPSWEEP: the death pipe is already in the reactor's watch
        set and is what normally reports a death (POLLHUP/POLLIN, and
        a death needs zero read syscalls), so this sweep is only a
        backstop. It was running on EVERY round with one waitpid per
        live worker — O(N) syscalls per round, regardless of how many
        records were flowing. bash's ring_poll has no equivalent: it
        builds its pollfd array once and lets poll() report liveness
        (forkrun_ring.c:8815), so the orchestrator does no reaping in
        its loop at all.

        At 79k batches that was 79554 waitpid calls, 0.06s, plus a
        list() copy of the workers dict per round. Throttle it: the
        death pipe still reports immediately, and _teardown_reactor
        does its own definitive per-slot reap, so nothing can be lost
        by sampling the backstop periodically instead of every round.
        ``force=True`` bypasses the throttle for callers that need an
        immediate answer.
        """
        if not force:
            # When nothing is alive the sweep is free (every slot is
            # skipped), and it is exactly the state a run winds down in --
            # so never throttle it, or the last round pays the full
            # interval as end-of-run latency for no saving.
            if not any(slot.alive for slot in self.workers.values()):
                pass
            else:
                now = _time.monotonic()
                if now - self._reap_last < _REAP_SWEEP_INTERVAL_S:
                    return
                self._reap_last = now
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


def _signal_ready(death_w):
    """Best-effort READY_BYTE write on the death pipe (W-REL6-3.1).

    Runs in the forked child once startup completes (C-loop children:
    after worker_init + setup, before the loop). The parent's startup
    deadline fires only for children that never get here. Never raises.
    """
    if death_w is not None and death_w >= 0:
        try:
            from ._worker import READY_BYTE as _READY
            os.write(death_w, _READY)
        except (OSError, ValueError):
            pass


def _splice_child_main(ctx, wid, node, incarn, death_w):
    """C-loop passthrough worker with death-pipe + trap-ACK (W-PY19).

    Runs in the forked child. Returns the exit code for os._exit.
    """
    from ._bindings import get as _get
    lib = _get()
    trap_w = ctx.get("trap_ack_w", -1)
    # W-PY21: best-effort pre-pinning (see spawn_worker).
    try:
        _ncpus = ctx.get("node_cpus")
        if _ncpus and 0 <= node < len(_ncpus):
            from ._numa import pin_to_node as _pin
            _pin(_ncpus[node])
    except Exception:
        pass
    try:
        # F-PORT1: poison threshold from FORKRUN_RETRY_LIMIT, never hardcoded.
        from ._api import _resolve_retry_limit as _retry_limit
        if lib.fr_py_worker_init(wid, node, incarn, _retry_limit(), 0) != 0:
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
        _signal_ready(death_w)
        rc = lib.fr_py_worker_splice_loop(
            wid, ctx["memfd"], out_fd, sig, fal)
    except BaseException:
        rc = 1
    if rc != 0:
        # W-REL2/R14a: never silent — refusal is announced
        # (parent-side recovery owns the batch); teardown continues.
        from ._worker import _escrow_deposit_exit_loud
        _escrow_deposit_exit_loud(lib, wid)
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


def _c_plugin_child_main(ctx, wid, node, incarn, death_w):
    """C-loop plugin worker with death-pipe + trap-ACK (W-PY26).

    Runs in the forked child. Returns the exit code for os._exit.
    Mirrors _splice_child_main: C loop owns claim→plugin→signal→ack;
    nonzero exit escrows in-flight work (safe-direction estimate)
    and trap-ACKs the wid for the reactor's grace.
    """
    from ._bindings import get as _get
    from ._worker import _ON_ERROR_CODES
    lib = _get()
    trap_w = ctx.get("trap_ack_w", -1)
    try:
        _ncpus = ctx.get("node_cpus")
        if _ncpus and 0 <= node < len(_ncpus):
            from ._numa import pin_to_node as _pin
            _pin(_ncpus[node])
    except Exception:
        pass
    try:
        spec = ctx.get("plugin_loop")
        path, func = (spec if isinstance(spec, (tuple, list)) and
                      len(spec) == 2 else (None, None))
        if not path or not func:
            return 1
        out_fds = ctx.get("out_fds") or []
        out_fd = (out_fds[wid] if out_fds and 0 <= wid < len(out_fds)
                  else -1)
        sig_w = ctx.get("signal_w", -1)
        sig = sig_w if sig_w is not None and sig_w >= 0 else -1
        fal_w = ctx.get("fallow_w", -1)
        fal = fal_w if fal_w is not None and fal_w >= 0 else -1
        ord_w = ctx.get("order_w", -1)
        ord_fd = ord_w if ord_w is not None and ord_w >= 0 else -1
        trap = trap_w if trap_w is not None and trap_w >= 0 else -1
        on_error = ctx.get("on_error", "retry")
        from ._api import _resolve_retry_limit as _retry_limit
        _signal_ready(death_w)
        rc = lib.fr_py_worker_plugin_loop(
            wid,
            path.encode("utf-8") if isinstance(path, str) else path,
            func.encode("utf-8") if isinstance(func, str) else func,
            ctx["memfd"], out_fd, sig, fal, ord_fd, trap, incarn,
            _retry_limit(),
            _ON_ERROR_CODES.get(on_error, 0))
    except BaseException:
        rc = 1
    if rc != 0:
        # W-REL2/R14a: never silent — refusal is announced
        # (parent-side recovery owns the batch); teardown continues.
        from ._worker import _escrow_deposit_exit_loud
        _escrow_deposit_exit_loud(lib, wid)
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


def _c_spawn_child_main(ctx, wid, node, incarn, death_w):
    """C-loop spawn worker with death-pipe + trap-ACK (W-PY33).

    Runs in the forked child. Returns the exit code for os._exit.
    Mirrors _c_plugin_child_main: C loop owns claim→spawn→signal→ack;
    nonzero exit escrows in-flight work (safe-direction estimate)
    and trap-ACKs the wid for the reactor's grace.
    """
    from ._bindings import get as _get
    from ._worker import _ON_ERROR_CODES
    lib = _get()
    trap_w = ctx.get("trap_ack_w", -1)
    try:
        _ncpus = ctx.get("node_cpus")
        if _ncpus and 0 <= node < len(_ncpus):
            from ._numa import pin_to_node as _pin
            _pin(_ncpus[node])
    except Exception:
        pass
    try:
        argv = ctx.get("spawn_loop")
        if not argv:
            return 1
        import ctypes as _ctypes
        _argv_b = [(a.encode("utf-8") if isinstance(a, str) else
                    bytes(a)) for a in list(argv)]
        argv_c = (_ctypes.c_char_p * (len(_argv_b) + 1))(
            *_argv_b, None)
        out_fds = ctx.get("out_fds") or []
        out_fd = (out_fds[wid] if out_fds and 0 <= wid < len(out_fds)
                  else -1)
        sig_w = ctx.get("signal_w", -1)
        sig = sig_w if sig_w is not None and sig_w >= 0 else -1
        fal_w = ctx.get("fallow_w", -1)
        fal = fal_w if fal_w is not None and fal_w >= 0 else -1
        ord_w = ctx.get("order_w", -1)
        ord_fd = ord_w if ord_w is not None and ord_w >= 0 else -1
        trap = trap_w if trap_w is not None and trap_w >= 0 else -1
        on_error = ctx.get("on_error", "retry")
        from ._api import _resolve_retry_limit as _retry_limit
        _signal_ready(death_w)
        rc = lib.fr_py_worker_spawn_loop(
            wid, argv_c, len(_argv_b),
            ctx["memfd"], out_fd, sig, fal, ord_fd, trap, incarn,
            _retry_limit(),
            _ON_ERROR_CODES.get(on_error, 0))
    except BaseException:
        rc = 1
    if rc != 0:
        # W-REL2/R14a: never silent — refusal is announced
        # (parent-side recovery owns the batch); teardown continues.
        from ._worker import _escrow_deposit_exit_loud
        _escrow_deposit_exit_loud(lib, wid)
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
        # W-PYSPAWNWIRE: hand each worker a wid that belongs to the
        # requested node, so wid_node stays authoritative (see
        # ReactorState.wid_node).
        if state.wid_node:
            # wid_free spans max_workers + num_nodes (spare capacity for
            # respawn/bump headroom) while wid_node only covers
            # max_workers, so bound the lookup: an unassigned spare wid
            # belongs to no node's block and must not be handed out here.
            _n = len(state.wid_node)
            _want = [w for w in sorted(state.wid_free)
                     if 0 <= w < _n and state.wid_node[w] == node]
            for _w in _want[:max(0, count)]:
                if state.spawn_worker(wid=_w, node=node) is None:
                    break
            return
        for _ in range(max(0, count)):
            if state.spawn_worker(node=node) is None:
                break


def reactor_loop(state, drain_gen=None, poll_timeout=0.1, service=None):
    """Supervise workers to completion (bash ring_poll equivalent).

    Death pipes + spawn pipe + trap-ACK pipe are select()ed each
    round; expirations raise RuntimeError (catastrophic: death
    without trap-ACK inside the grace). drain_gen (optional) is a
    zero-arg callable returning the next result blob, None when no
    complete record is available YET (not EOF — the loop keeps
    polling), or raising StopIteration when the stream is exhausted:
    while any worker is alive the loop pumps it and YIELDS each blob
    (streaming mode); when drain_gen is None the loop only
    supervises (map/run mode). service (optional) is a zero-arg
    callable run once per round after event handling (NUMA helper
    watches — pipeline deaths raise promptly instead of waiting
    for worker completion).

    Yields result blobs (streaming) and returns
    {"statuses": [(pid, status)], "poisoned": [...]}.
    Raises RuntimeError on trap-ACK timeout. Never returns while a
    worker is alive.
    """
    drained_last = False

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
        # W-REL6-3.1: startup deadline (a hung child shows neither
        # readiness nor death -- SIGKILL it so the reap/respawn path
        # bounds the hang instead of select() waiting forever).
        state.check_startup_timeouts()

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
                # Adaptive idle: a round that drained results
                # re-polls immediately (tight drain loop under load)
                # instead of sleeping a full quantum with data
                # waiting — otherwise throughput caps at ~10
                # blobs/s (one yield per 100ms idle select).
                readable, _, _ = _select.select(
                    watch, [], [],
                    0.0 if drained_last else poll_timeout)
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
                    # Readable death pipe: EOF means the worker is
                    # gone (the non-blocking poll twin reaps it --
                    # W-REL5-B5: EOF precedes os._exit, so a
                    # descheduled child defers to the sweep instead
                    # of stalling the loop).
                    # W-REL6-3.1: the one exception is READY_BYTE --
                    # the startup handshake. note_ready consumes it
                    # (marking the worker ready) and reports True;
                    # only EOF (False) runs the death path below.
                    try:
                        _chunk = os.read(fd, 4096)
                    except OSError:
                        _chunk = b""
                    if state.note_ready(wid, _chunk):
                        continue
                    kind, _new = state.worker_died_poll(wid)
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

        # 3b. Owner service hook (NUMA pipeline watches). Raises
        #    propagate (helper death aborts the supervised run).
        if service is not None:
            service()

        # 4. Streaming drain pump (None = nothing complete YET,
        #    keep polling; StopIteration = stream exhausted for good).
        #    Bounded burst per round (DRAIN_BURST): one blob per
        #    round starves throughput (see above); an unbounded
        #    burst would starve death handling under a flooding
        #    stream. 64 bounds detection latency while draining
        #    any realistic backlog per round.
        if drain_gen is not None:
            drained_last = False
            for _ in range(DRAIN_BURST):
                try:
                    blob = drain_gen()
                except StopIteration:
                    drain_gen = None
                    break
                if blob is None:
                    break
                drained_last = True
                yield blob
            if drained_last:
                # Re-check timeouts promptly after a burst rather
                # than sleeping a full quantum with a dead grace.
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


def reactor_run(state, poll_timeout=0.1, service=None):
    """Blocking supervision (map/run): exhaust reactor_loop, return its
    result dict. Raises RuntimeError on trap-ACK timeout."""
    gen = reactor_loop(state, None, poll_timeout, service)
    try:
        while True:
            next(gen)
    except StopIteration as _stop:
        if isinstance(_stop.value, dict):
            return _stop.value
    return {"statuses": list(state.statuses),
            "poisoned": list(state.poisoned_batches)}


def reactor_poll_once(state, poll_timeout=0.0, spawn=True):
    """Service one nonblocking event round (spill-loop interleaving).

    Runs a single select round over death/spawn/trap-ACK pipes plus
    the timeout check and the out-of-band reap sweep. Used by
    blocking ingest paths that must supervise workers WHILE spilling
    synchronously (they cannot enter reactor_run until the spill and
    gate are done). Blocks at most poll_timeout plus the bounded
    death-confirm spin (DEATH_CONFIRM_SPIN_S — W-REL5-B5: death-pipe
    EOF precedes os._exit, so an unreaped child defers to the sweep
    instead of stalling the spill). Raises RuntimeError on
    trap-ACK timeout.

    ``spawn=False`` leaves the scanner's spawn pipe out of the watch
    set for this round (W-PYSPAWNWIRE). The NUMA fork gate calls this to
    supervise helpers while it decides its forks, and servicing spawn
    requests there would fork workers the gate's own ``forked`` set
    never records -- the gate then exits with ``forked`` empty and the
    run dies on a false "ingest landed N bytes with no published
    batches". Suppressing the watch entry (rather than blanking
    state.spawn_r around the gate) keeps the descriptor parked on state
    for teardown, so it cannot leak on any early-error path.
    """
    state.check_trap_timeouts()
    # W-REL6-3.1: startup deadline also bounds spill-loop supervision
    # (a hung child would otherwise stall the spill, not just the run).
    state.check_startup_timeouts()
    watch = []
    death_of = {}
    for slot in state.workers.values():
        if slot.alive and slot.death_r is not None and slot.death_r >= 0:
            watch.append(slot.death_r)
            death_of[slot.death_r] = slot.wid
    if spawn and state.spawn_r is not None and state.spawn_r >= 0:
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
                    chunk = os.read(fd, 4096)
                except OSError:
                    chunk = b""
                # W-REL6-3.1: READY_BYTE is the startup handshake,
                # not a death -- note_ready consumes it; only EOF
                # runs the reap path.
                if state.note_ready(wid, chunk):
                    continue
                # W-REL5-B5: the non-blocking twin — worker_died
                # would block here on a descheduled child (EOF
                # precedes os._exit), contradicting this function's
                # contract and stalling the spill loop.
                state.worker_died_poll(wid)
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
           "TRAP_ACK_GRACE_S", "ORDER_PIPE_SIZE", "DRAIN_BURST"]
