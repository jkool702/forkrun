#!/usr/bin/env python3
"""Stage 0 endless pipe-stream generator (for the TB-streaming niche).

Emits fixed 8 KiB blocks with an 8-byte LE sequence number at each block
start, forever. The body block is precomputed once; only the 8-byte header
is rewritten per block (one slice assignment per 8 KiB). Consumers take
`head -c N`. Exceeds RAM by construction (no file ever exists).

Usage: python3 gen_stream.py > pipe  (consumer: head -c N)
"""
from __future__ import annotations

import struct
import sys

BLOCK = 8192


def main() -> None:
    out = sys.stdout.buffer
    body = b"S" * (BLOCK - 8)
    seq = 0
    write = out.write
    try:
        while True:
            write(struct.pack("<Q", seq))
            write(body)
            seq += 1
    except BrokenPipeError:
        # Consumer took what it needed (head -c); silent exit.
        pass


if __name__ == "__main__":
    main()
