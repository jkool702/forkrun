"""forkrun Python frontend package (Stage 0 stub)."""

from forkrun._api import RunConfig  # noqa: F401
from forkrun._api import _validate as _validate_config  # noqa: F401


def run(payload, source, *, mode="python", sink=None, order="none",
        lines=None, bytes=None, workers=None, nodes="auto",
        on_error="retry"):
    """v1.3 §3.0 v0 public API — signature frozen for Stage 0 measurement.

    Stage 0 stub: validates arguments, then raises NotImplementedError.
    Stage 4 wires the substrate.
    """
    _validate_config(payload, source, mode=mode, sink=sink, order=order,
                     lines=lines, bytes_=bytes, workers=workers, nodes=nodes,
                     on_error=on_error)
    raise NotImplementedError("forkrun.run() engine binding lands in Stage 4")


def map(func, source, **kwargs):
    """Thin convenience wrapper over run()."""
    return run(func, source, **kwargs)


def stream(func, source, **kwargs):
    """Thin convenience wrapper over run()."""
    return run(func, source, **kwargs)


__all__ = ["run", "map", "stream", "RunConfig"]
