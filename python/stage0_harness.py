# Stage 0 falsification-gate harness skeleton (v1.3 §2).
#
# The gate must measure the shipping surface (§3.0 API) per niche:
#   Throughput per niche | Peak RSS vs stream size | Fault isolation
#       (empirical, incumbent-specific) | Injection (SIGSEGV workload)
# Columns: niche, incumbent baseline, forkrun result, RSS, fault outcome,
#   hardware disclosure.
# Exit: compelling niche -> proceed (noting which); nothing anywhere -> stop.
#
# This skeleton defines the table schema and validates the API surface
# imports cleanly. Stage 0 proper fills each row with measured numbers.
"""Stage 0 harness skeleton: schema + surface check, no measurements yet."""

from __future__ import annotations

import csv
import os
import platform
import sys

NICHES = (
    "jsonl-ingest",
    "tokenize-to-tensor",
    "per-record-transform",
    "tb-streaming",
)

TABLE_COLUMNS = (
    "niche",
    "incumbent",
    "incumbent_result",
    "forkrun_result",
    "peak_rss_mb",
    "fault_outcome",
    "hardware",
)

STRONG_WIN_THRESHOLD = "3-5x per niche (strong-win threshold, not minimum viability)"


def _cpu_model() -> str:
    """CPU model string, with a non-x86 fallback.

    x86 /proc/cpuinfo exposes "model name"; aarch64 exposes "CPU part"
    instead, so the old x86-only lookup reported `unknown-cpu` on the ARM leg.
    The hardware column is the gate's disclosure mechanism, so losing it on an
    arch would defeat the column's purpose.
    """
    fields: dict[str, str] = {}
    try:
        with open("/proc/cpuinfo") as fh:
            for ln in fh:
                key, sep, val = ln.partition(":")
                if not sep:
                    continue
                key = key.strip()
                if key in ("model name", "CPU part") and key not in fields:
                    fields[key] = val.strip()
    except OSError:
        pass
    for key in ("model name", "CPU part"):
        if fields.get(key):
            return fields[key]
    return platform.processor() or "unknown-cpu"


def hardware_label() -> str:
    """Hardware disclosure column value for this machine."""
    return (f"{platform.node()} | {_cpu_model()} | {platform.machine()} | "
            f"{platform.python_version()}")


def check_surface() -> list[str]:
    """Import the shipping surface and exercise validation (no engine)."""
    errors: list[str] = []
    # Import from THIS file's directory, not the CWD-relative "python" (the
    # harness is runnable from anywhere).
    pkg_root = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, pkg_root)
    try:
        import forkrun  # noqa: PLC0415
        # Validation paths must work pre-engine:
        try:
            forkrun.run("pkg.mod:func", source=[1, 2, 3])
            errors.append("iterable source was NOT rejected")
        except TypeError:
            pass
        try:
            forkrun.run("pkg.mod:func", source="in.txt", mode="bogus")
            errors.append("bad mode was NOT rejected")
        except ValueError:
            pass
        try:
            forkrun.run("pkg.mod:func", source="in.txt")
            errors.append("run() with valid args returned unexpectedly")
        except NotImplementedError:
            pass  # no engine built: validation passed, binding deferred
        except (FileNotFoundError, OSError, RuntimeError):
            pass  # engine built (W-PY1): validation passed, engine tried
            # ("in.txt" is missing / the dummy payload unimportable)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"surface import/validation failed: {exc}")
    finally:
        try:
            sys.path.remove(pkg_root)
        except ValueError:
            pass
    return errors


def write_empty_table(path: str) -> None:
    with open(path, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=TABLE_COLUMNS)
        writer.writeheader()
        for niche in NICHES:
            writer.writerow({
                "niche": niche,
                "incumbent": "TBD",
                "incumbent_result": "TBD",
                "forkrun_result": "UNMEASURED",
                "peak_rss_mb": "UNMEASURED",
                "fault_outcome": "UNMEASURED",
                "hardware": hardware_label(),
            })


if __name__ == "__main__":
    errs = check_surface()
    if errs:
        print("SURFACE CHECK FAILED:")
        for err in errs:
            print(f"  - {err}")
        raise SystemExit(1)
    out = sys.argv[1] if len(sys.argv) > 1 else "python/stage0_table.csv"
    write_empty_table(out)
    print(f"surface OK; empty Stage 0 table written to {out}")
    print(f"strong-win threshold: {STRONG_WIN_THRESHOLD}")
