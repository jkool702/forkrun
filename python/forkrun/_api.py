"""forkrun Python frontend — Stage 0 API surface stub (v1.3 §3.0).

This module defines the SHIPPING SURFACE that the Stage 0 falsification
gate measures. It intentionally contains no engine changes: every call
validates its arguments (including the source/sink plumbing shape) and
then raises NotImplementedError until Stage 4 wires the substrate.

The gate must measure the shipping surface — including how `source=`
and `sink=` plumb — or it validates an API that won't ship.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Literal, Optional, Union
import io
import os

Mode = Literal["python", "spawn", "plugin", "splice"]
Order = Literal["none", "index"]
OnError = Literal["retry", "fail-fast", "skip"]
# W-PY21: "auto"/None (detect), 1 (UMA), N (first N physicals),
# "0,1" (explicit physicals), "@N" (forced logical nodes).
Nodes = Union[int, str, None]

_VALID_MODES = ("python", "spawn", "plugin", "splice")
_VALID_ORDERS = ("none", "index")
_VALID_ON_ERROR = ("retry", "fail-fast", "skip")


def _reject_iterable_source(source: Any) -> None:
    """Reject iterables/generators with the stated reason.

    An iterator would make the Python interpreter part of the ingestion
    datapath, destroying the engine's ability to maintain bounded,
    kernel-fed streaming independently of Python scheduling. Python is
    never an input pump.
    """
    # bool is an int subclass and would otherwise sail straight through as a
    # file descriptor (True == fd 1 == stdout). It is never a real source.
    if isinstance(source, bool):
        raise TypeError(
            "forkrun.run() source must be path | fd | pipe/socket (object with "
            f"fileno()); got bool ({source!r}) — bool is an int subclass but is "
            "not a file descriptor"
        )
    # Allowed: path-like, non-negative int fd, file/socket objects with fileno().
    if isinstance(source, (str, bytes, os.PathLike)):
        return
    if isinstance(source, int):
        if source >= 0:
            return
        raise TypeError(
            "forkrun.run() source fd must be non-negative, "
            f"got {source!r} — negative values are not open descriptors"
        )
    if hasattr(source, "fileno"):
        try:
            fd = source.fileno()
        except (io.UnsupportedOperation, OSError):
            pass
        else:
            if isinstance(fd, int) and not isinstance(fd, bool) and fd >= 0:
                return
    raise TypeError(
        "forkrun.run() source must be path | fd | pipe/socket (object with "
        "fileno()); iterables/generators are rejected: Python is never an "
        "input pump — an iterator would make the Python interpreter part of "
        "the ingestion datapath, destroying bounded kernel-fed streaming, "
        f"got {type(source).__name__}"
    )


@dataclass
class RunConfig:
    payload: Any
    source: Any
    mode: Mode = "python"
    sink: Optional[Callable[..., Any]] = None
    order: Order = "none"
    lines: Optional[int] = None
    bytes: Optional[int] = None
    workers: Optional[int] = None
    nodes: Nodes = "auto"
    on_error: OnError = "retry"
    streaming: Optional[bool] = None
    # W-PY22 resume: checkpoint file to resume FROM (byte coordinates)
    # and/or checkpoint file to publish TO on abort. Path gating
    # (C-orderer executors only) happens in run.py — here only the
    # shape is validated (str/PathLike or None; resume must exist).
    resume: Optional[Any] = None
    checkpoint_file: Optional[Any] = None


def _validate_resume_path(name: str, value: Any, must_exist: bool) -> Any:
    """Validate a resume/checkpoint file path (W-PY22).

    Returns the path as str. must_exist (resume=) raises
    FileNotFoundError eagerly; checkpoint_file= may not exist yet
    (created atomically on abort).
    """
    if isinstance(value, os.PathLike):
        value = os.fspath(value)
    if not isinstance(value, str):
        raise TypeError(
            f"{name} must be a file path (str), got "
            f"{type(value).__name__}")
    if not value:
        raise ValueError(f"{name} must be a non-empty path")
    if must_exist and not os.path.exists(value):
        raise FileNotFoundError(
            f"checkpoint file not found: {value!r}")
    return value


def _validate(payload: Any, source: Any, *, mode: str, sink: Any,
              order: str, lines: Any, bytes_: Any, workers: Any,
              nodes: Any, on_error: str, streaming: Any = None,
              resume: Any = None, checkpoint_file: Any = None) -> RunConfig:
    if mode not in _VALID_MODES:
        raise ValueError(f"mode must be one of {_VALID_MODES}, got {mode!r}")
    if order not in _VALID_ORDERS:
        raise ValueError(f"order must be one of {_VALID_ORDERS}, got {order!r}")
    if on_error not in _VALID_ON_ERROR:
        raise ValueError(f"on_error must be one of {_VALID_ON_ERROR}, got {on_error!r}")
    if lines is not None and bytes_ is not None:
        raise ValueError("lines= and bytes= are mutually exclusive (-l / -b analogues)")
    for name, val in (("lines", lines), ("bytes", bytes_), ("workers", workers)):
        if val is not None and (not isinstance(val, int) or val <= 0):
            raise ValueError(f"{name} must be a positive int, got {val!r}")
    # W-PY21 NUMA node specs: None/"auto" (detect), 1/"1" (UMA),
    # N (first N physicals), "0,1" (explicit), "@N" (forced logical).
    # Full resolution lives in _numa.build_numa_map; validated here
    # so run/map/stream all fail eagerly on bad specs.
    try:
        from forkrun._numa import build_numa_map as _build_map
        _build_map(nodes)
    except ValueError as exc:
        raise ValueError(f"nodes: {exc}")
    if sink is not None and not callable(sink):
        raise TypeError(f"sink must be None or callable on_batch(batch_meta, result), got {type(sink).__name__}")
    if streaming is not None and not isinstance(streaming, bool):
        raise TypeError(f"streaming must be None, True, or False, got {streaming!r}")
    if mode == "splice":
        # Passthrough has no payload hook: payload must be absent (an
        # ignored payload would silently drop user code — reject the
        # contradiction instead), no sink (nothing calls it), and byte
        # batching only (lines= are boundaries the loop never detects).
        if payload is not None:
            raise ValueError(
                "mode='splice' takes no payload (passthrough) — got %r; "
                "pass payload=None" % (payload,))
        if sink is not None:
            raise ValueError(
                "mode='splice' takes no sink (no per-batch Python hook)")
        if lines is not None:
            raise ValueError(
                "mode='splice' requires bytes=N (byte batches), not "
                "lines=N (line boundaries are never detected)")
    elif payload is None:
        raise ValueError("payload is required: 'pkg.mod:func' | callable | 'plugin.so:fn'")
    _reject_iterable_source(source)
    resume_path = (None if resume is None
                   else _validate_resume_path("resume", resume, True))
    checkpoint_path = (None if checkpoint_file is None
                       else _validate_resume_path(
                           "checkpoint_file", checkpoint_file, False))
    return RunConfig(payload=payload, source=source, mode=mode, sink=sink,
                     order=order, lines=lines, bytes=bytes_, workers=workers,
                     nodes=nodes, on_error=on_error, streaming=streaming,
                     resume=resume_path, checkpoint_file=checkpoint_path)
