"""Parameter sweeps: Cartesian products or zipped argument lists (W-PY20).

Bash equivalents:
  frun process ::: a b c ::: x y       # Cartesian (6 combos)
  frun process --link ::: a b ::: x y  # Zip (paired combos)
  frun process :::: file1 :::: file2   # Dimensions from files

Python:
  forkrun.sweep(payload, args=[["a", "b", "c"], ["x", "y"]])
  forkrun.sweep(payload, args=[["a", "b"], ["x", "y"]], link=True)
  forkrun.sweep(payload, args_from=["file1.txt", "file2.txt"])

Pure frontend feature: the engine never sees sweeps (each combination
becomes ordinary batches with metadata carrying the sweep tuple).
No engine changes, no new syscalls, no IPC beyond the existing pipes.
"""

from __future__ import annotations

import itertools
import warnings


def generate_combinations(args=None, args_from=None, link=False):
    """Generate argument combinations (lazy iterator of tuples).

    args: list of lists — each inner list is one sweep dimension.
      Elements are opaque (usually strings); each combination is one
      tuple with one entry per dimension, in dimension order.
    args_from: list of file paths — each file provides one dimension
      (one value per line; blank lines skipped).
    link: False (default) = Cartesian product (bash `:::`); True =
      zip dimensions pairwise (bash `--link`).

    Returns an iterator of tuples (possibly empty). Single dimension
    yields 1-tuples; an empty dimension (or no dimensions) yields no
    combinations.

    Raises ValueError if both/neither of args=/args_from= is given,
    if a dimension is not a list/tuple, or if an args_from= file
    cannot be read. Unequal lengths in link mode truncate to the
    shortest with a UserWarning (bash `--link` requires equal
    lengths and errors; truncation-with-warning is the documented
    Python choice — loudly visible, never silent).
    """
    if args is not None and args_from is not None:
        raise ValueError("Provide either args= or args_from=, not both")
    if args is None and args_from is None:
        raise ValueError("Either args= or args_from= is required")

    if args is not None:
        if isinstance(args, str) or not isinstance(args, (list, tuple)):
            raise ValueError(
                "args= must be a list of lists (one per dimension), "
                "got %r" % (args,))
        for d in args:
            # A bare string dimension is almost certainly a user
            # error (strings iterate as chars) — reject loudly.
            if isinstance(d, str) or not isinstance(d, (list, tuple)):
                raise ValueError(
                    "each sweep dimension must be a list/tuple, got %r"
                    % (d,))
        dimensions = [list(d) for d in args]
    else:
        dimensions = []
        for path in args_from:
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    dim = [line.rstrip("\n").rstrip("\r")
                           for line in fh]
            except OSError as exc:
                raise ValueError(
                    "cannot read sweep dimension file %r: %s"
                    % (path, exc))
            dimensions.append([v for v in dim if v.strip() != ""])

    if not dimensions:
        return iter([])
    if any(len(d) == 0 for d in dimensions):
        return iter([])

    if link:
        lengths = [len(d) for d in dimensions]
        if len(set(lengths)) > 1:
            warnings.warn(
                "Parameter sweep dimensions have different lengths "
                "(%s). Truncating to shortest (%d)."
                % (lengths, min(lengths)), UserWarning, stacklevel=2)
        return iter(zip(*dimensions))
    return iter(itertools.product(*dimensions))


__all__ = ["generate_combinations"]
