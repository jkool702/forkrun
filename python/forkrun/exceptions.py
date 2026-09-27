"""Cause-fidelity exception taxonomy (D-PORT3).

A Python library's interface contract is *exceptions*, not process
exit status — so parity with the Bash exit-code taxonomy (primer
§3: 130/143/138/3/42/200/254, ``&0xFF``) means **cause fidelity,
not number fidelity**. Every abort cause the Bash parent reports
as a signal-derived exit code surfaces here as a distinct
exception class carrying the ``signo`` and the Bash code it
corresponds to (``bash_code``), plus the user remedy in the
message. Engine faults with no signal cause (claim race, orphan
revert failure, trap-ACK timeout, worker crash) stay plain
``RuntimeError`` (Bash ``exit 1``) — see the mapping table in
``python/docs/TROUBLESHOOTING.md``.

``ForkrunInterrupted`` subclasses *both* ``ForkrunSignalError``
(``RuntimeError`` — so existing ``except RuntimeError`` callers
keep working) and ``KeyboardInterrupt`` (so existing ``except
KeyboardInterrupt`` callers — including the W-PY22 SIGINT
abort→checkpoint→resume contract — keep working, and so the
interruption is never swallowed by a generic ``except
Exception``-and-continue the way Bash's foreground-only 130 is
never downgraded by a concurrent SIGPIPE).
"""

from __future__ import annotations

import signal as _signal


class ForkrunSignalError(RuntimeError):
    """Base for signal-caused aborts. ``signo`` is the POSIX signal
    number (or None when synthesized); ``bash_code`` is the Bash
    exit code this cause corresponds to (or None)."""

    bash_code = None

    def __init__(self, msg, *, signo=None):
        super().__init__(msg)
        self.signo = signo


class ForkrunInterrupted(ForkrunSignalError, KeyboardInterrupt):
    """Operator SIGINT / Ctrl-C in the parent (Bash: exit 130,
    foreground-only). Also a ``KeyboardInterrupt``, so parent-side
    interruption keeps standard Python semantics."""

    bash_code = 130

    def __init__(self, msg, *, signo=int(_signal.SIGINT)):
        super().__init__(msg, signo=signo)


class ForkrunPreempted(ForkrunSignalError):
    """Scheduler preemption notice (SIGUSR1) received while
    ``FORKRUN_PREEMPT_MODE=1`` (Bash: exit 138). Only installed by
    the opt-in ``signal_policy="checkpoint"`` path, and only when
    preemption mode is armed — mirroring the Bash conditional
    trap."""

    bash_code = 138


class ForkrunTerminated(ForkrunSignalError):
    """Operator/overlord SIGTERM or SIGHUP in the parent (Bash:
    exit 143 for TERM; HUP aborts into the checkpoint path).
    Raised *after* abort teardown and any armed checkpoint
    publication, so resuming from the checkpoint is immediately
    valid."""

    bash_code = 143


class ForkrunPoisonSkip(RuntimeError):
    """One or more batches crossed the poison threshold and were
    skipped (Bash: exit 3). Raised only under opt-in
    ``strict_poison=True``; the default stays warn-and-return-
    partial (Bash ``-E`` continuation semantics). ``count`` is the
    engine's poisoned-batch total."""

    bash_code = 3

    def __init__(self, msg, *, count=0):
        super().__init__(msg)
        self.count = count


#: Bash exit code -> Python exception (cause fidelity, not number
#: fidelity). Codes without a signal cause (1, 42, 200/254) stay
#: plain RuntimeError/SpawnError/PluginError by design.
BASH_CODE_MAP = {
    130: ForkrunInterrupted,
    138: ForkrunPreempted,
    143: ForkrunTerminated,
    3: ForkrunPoisonSkip,
}


__all__ = ["ForkrunSignalError", "ForkrunInterrupted",
           "ForkrunPreempted", "ForkrunTerminated",
           "ForkrunPoisonSkip", "BASH_CODE_MAP"]
