"""Mode 2 (spawn): execute external binaries per batch (W-PY8, W-PY13).

Two dispatch tiers (chosen per worker in _worker.py, not here):
- v1 (W-PY13): C-level fr_py_exec_spawn — posix_spawnp with a concurrent
  poll pump (splice ingress memfd -> stdin, stdout pipe -> output memfd,
  framed in C). ~10µs overhead. Active when the substrate exports the
  symbol, a sink isn't consuming the output, and an output memfd exists.
  The closure below is then only a marker: _worker reads
  _forkrun_spawn_argv and never calls the function (zero-copy input —
  batch.data is never touched).
- v0: Python subprocess.run per batch (~350µs overhead). Fallback when
  v1 is unavailable (pre-v1 .so, FORKRUN_NO_V1=1, run() with sink=, or
  run() discard mode with no output memfd).

Timeout note: v0 enforces a fixed 30s per-batch timeout below; v1 waits
like bash -X does (no timeout — a hung command hangs the worker, whose
nonzero/signal death then rides the normal escrow/retry path).

Performance note: v1 spawn pays ~10us per-batch (posix_spawnp + splice
pump) vs v0's ~350µs subprocess overhead — the bash -X gap is closed
while keeping v0 as the fallback.

Purity note: the run() call below transports batch bytes INTO the child
via a stdin pipe — inherent to exec mode (the command reads stdin) and
explicitly sanctioned by the work order. The §3.9 no-Python-IPC rule
governs the RESULT path (captured stdout crosses back via the same
return channel as Python payloads: copied to the output memfd by the
worker wrapper). This module is therefore OUTSIDE the purity-test scan
list (see test_v0.TestPurity): its stdlib process-launch use is
execution, not transport. No pickling, no bash, no shell execution
anywhere here.
"""

from __future__ import annotations

import subprocess

_TIMEOUT_S = 30  # v0: fixed per-batch timeout (configurable in v1)


class SpawnError(Exception):
    """External command failed (non-zero exit, timeout, or spawn failure).

    Always retriable through the existing escrow/retry/poison path
    (bash -E semantics). Known-fatal errors (e.g. command not found)
    also ride retry-then-poison in v0 — wasteful but correct;
    fast-poison is a v1 optimization.
    """


def make_spawn_payload(command):
    """Build a forkrun payload function around an external command.

    command: str (split on whitespace, shell=False) or list/tuple
      (used directly as argv). Use list form for anything quoting would
      be needed for — str.split() does no shell parsing.
    Returns a payload fn: batch -> stdout bytes (raises SpawnError on
      non-zero exit, timeout, or spawn failure).
    """
    if isinstance(command, str):
        argv = command.split()
        if not argv:
            raise ValueError("mode='spawn' command string is empty")
    elif isinstance(command, (list, tuple)):
        argv = list(command)
        if not argv:
            raise ValueError("mode='spawn' command list is empty")
    else:
        raise ValueError(
            "mode='spawn' requires a command (str or list), got %s"
            % type(command).__name__)

    def spawn_payload(batch):
        try:
            result = subprocess.run(
                argv,
                input=bytes(batch.data),  # copy out of the shared window
                capture_output=True,
                timeout=_TIMEOUT_S,
            )
        except subprocess.TimeoutExpired:
            raise SpawnError(
                "command %r timed out after %ds" % (argv, _TIMEOUT_S))
        except FileNotFoundError:
            raise SpawnError("command not found: %r" % (argv[0],))
        except OSError as exc:
            raise SpawnError("spawn failed for %r: %s" % (argv, exc))
        if result.returncode != 0:
            raise SpawnError(
                "command %r exited with %d: %s" % (
                    argv, result.returncode,
                    result.stderr.decode("utf-8", errors="replace")[:200]))
        return result.stdout

    spawn_payload._forkrun_spawn_argv = argv  # introspection/testing
    return spawn_payload


__all__ = ["make_spawn_payload", "SpawnError"]
