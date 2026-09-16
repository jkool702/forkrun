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

Mode = Literal["python", "spawn", "plugin"]
Order = Literal["none", "index"]
OnError = Literal["retry", "fail-fast", "skip"]
Nodes = Union[int, Literal["auto"]]

_VALID_MODES = ("python", "spawn", "plugin")
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


def _validate(payload: Any, source: Any, *, mode: str, sink: Any,
              order: str, lines: Any, bytes_: Any, workers: Any,
              nodes: Any, on_error: str) -> RunConfig:
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
    if not (nodes == "auto" or (isinstance(nodes, int) and nodes >= 1)):
        raise ValueError(f'nodes must be "auto" or a positive int, got {nodes!r}')
    if sink is not None and not callable(sink):
        raise TypeError(f"sink must be None or callable on_batch(batch_meta, result), got {type(sink).__name__}")
    if payload is None:
        raise ValueError("payload is required: 'pkg.mod:func' | callable | 'plugin.so:fn'")
    _reject_iterable_source(source)
    return RunConfig(payload=payload, source=source, mode=mode, sink=sink,
                     order=order, lines=lines, bytes=bytes_, workers=workers,
                     nodes=nodes, on_error=on_error)
