"""forkrun Python frontend package (Stage 0 stub).

Naming note: this is a namespaced API, so `forkrun.map` deliberately shadows
the builtin `map` *inside this namespace only* (`forkrun.map(...)`, never a
bare `map(...)`). The alias is chosen to match the mental model of the
incumbents we benchmark against (`ProcessPoolExecutor.map`, `joblib`, and the
DataLoader idiom), which is the point of the convenience wrappers. `import
forkrun` does not shadow anything at the call site of the importer.
"""

from forkrun._api import RunConfig  # noqa: F401
# Private in _api (not part of the v0 surface); re-exported here only so the
# Stage 0 harness and tests can assert validation without reaching into _api.
from forkrun._api import _validate as _validate_config  # noqa: F401


def run(payload, source, *, mode="python", sink=None, order="none",
        lines=None, bytes=None, workers=None, nodes="auto",
        on_error="retry"):
    """v1.3 §3.0 v0 public API — signature frozen for Stage 0 measurement.

    Stage 0 stub: validates arguments, then raises NotImplementedError.
    Stage 4 wires the substrate.

    NOTE: the `bytes=` keyword deliberately shadows the builtin `bytes` inside
    this function only. It is inherited from the frozen §3.0 API sketch (the
    -l / -b analogues) and kept for plan fidelity; use `builtins.bytes` if this
    body ever needs the builtin.
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
