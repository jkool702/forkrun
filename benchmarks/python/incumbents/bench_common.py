#!/usr/bin/env python3
"""Stage 0 shared measurement helpers (stdlib only).

Every incumbent script prints exactly one JSON summary line on stdout:
{"niche","incumbent","input_bytes","elapsed_s","peak_rss_mb",
 "output_checksum","notes"}. Human diagnostics go to stderr.
"""
from __future__ import annotations

import hashlib
import json
import os
import resource
import sys
import time


def now() -> float:
    return time.monotonic()


def peak_rss_mb() -> float:
    """Max RSS (MiB) of self + waited-for children (pool workers)."""
    me = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    try:
        kids = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    except Exception:
        kids = 0
    # Linux ru_maxrss is KiB; macOS bytes. This harness is Linux-only.
    return round(max(me, kids) / 1024.0, 1)


class Hasher:
    def __init__(self) -> None:
        self._h = hashlib.sha256()
        self.n_bytes = 0

    def update(self, data: bytes) -> None:
        self._h.update(data)
        self.n_bytes += len(data)

    def hexdigest(self) -> str:
        return self._h.hexdigest()


def emit(niche: str, incumbent: str, input_bytes: int, elapsed_s: float,
         output_checksum: str, notes: str = "") -> None:
    print(json.dumps({
        "niche": niche,
        "incumbent": incumbent,
        "input_bytes": input_bytes,
        "elapsed_s": round(elapsed_s, 3),
        "peak_rss_mb": peak_rss_mb(),
        "output_checksum": output_checksum,
        "notes": notes,
    }), flush=True)


def emit_unmeasured(niche: str, incumbent: str, reason: str) -> None:
    print(json.dumps({
        "niche": niche,
        "incumbent": incumbent,
        "input_bytes": 0,
        "elapsed_s": 0.0,
        "peak_rss_mb": 0.0,
        "output_checksum": "UNMEASURED",
        "notes": reason,
    }), flush=True)
