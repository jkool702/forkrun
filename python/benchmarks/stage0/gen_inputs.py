#!/usr/bin/env python3
"""Stage 0 deterministic input generators (seeded, documented sizes).

Usage:
    python3 gen_inputs.py --out DIR [--only JSONL|TOKENS|TRANSFORM]

Niche inputs (all reproducible from SEED):
  jsonl_1M.jsonl      1,000,000 JSON records, one per line (~130 MB).
                      Record: {"id":i,"user":"user-<i>","score":f,"tags":[...]}
  tokens_100M.i32     100,000,000 int32 LE tokens, vocab [0, 50000) (400 MB).
                      Seeded numpy RNG; sha recorded in manifest.
  transform_10M.txt   10,000,000 lines "item-<i>" (~89 MB).
  stream (pipe)       No file: gen_stream.py emits fixed 8 KiB blocks of 'S'
                      with an 8-byte LE sequence number per block, forever.
                      Consumers take head -c N. Exceeds RAM by construction.

A manifest.json records {file, bytes, sha256, seed, generator} per input.
Only manifest + sizes are read back by the harness (context hygiene:
never cat input files).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys

SEED = 20260919

JSONL_RECORDS = 1_000_000
TOKENS_N = 100_000_000
TOKENS_VOCAB = 50_000
TRANSFORM_ITEMS = 10_000_000


def sha_of(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def gen_jsonl(path: str) -> None:
    import random
    rng = random.Random(SEED)
    with open(path, "w", encoding="ascii") as fh:
        wr = fh.write
        for i in range(JSONL_RECORDS):
            score = round(rng.uniform(0, 100), 3)
            tags = ["t%d" % rng.randrange(20) for _ in range(rng.randrange(1, 4))]
            wr('{"id":%d,"user":"user-%d","score":%s,"tags":[%s]}\n' % (
                i, i, score, ",".join('"%s"' % t for t in tags)))


def gen_tokens(path: str) -> None:
    import numpy as np
    rng = np.random.default_rng(SEED)
    chunk = 10_000_000
    with open(path, "wb") as fh:
        for _ in range(TOKENS_N // chunk):
            fh.write(rng.integers(0, TOKENS_VOCAB, size=chunk,
                                  dtype=np.int32).tobytes())


def gen_transform(path: str) -> None:
    with open(path, "w", encoding="ascii") as fh:
        wr = fh.write
        for i in range(TRANSFORM_ITEMS):
            wr("item-%d\n" % i)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--only", default="",
                    choices=("", "JSONL", "TOKENS", "TRANSFORM"))
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    manifest: dict[str, dict] = {}
    jobs = []
    if args.only in ("", "JSONL"):
        jobs.append(("jsonl_1M.jsonl", gen_jsonl))
    if args.only in ("", "TOKENS"):
        jobs.append(("tokens_100M.i32", gen_tokens))
    if args.only in ("", "TRANSFORM"):
        jobs.append(("transform_10M.txt", gen_transform))
    for name, fn in jobs:
        path = os.path.join(args.out, name)
        print(f"gen {name} ...", flush=True)
        fn(path)
        manifest[name] = {"bytes": os.path.getsize(path),
                          "sha256": sha_of(path), "seed": SEED}
        print(f"  {manifest[name]['bytes']} bytes sha={manifest[name]['sha256'][:16]}...",
              flush=True)
    mpath = os.path.join(args.out, "manifest.json")
    with open(mpath, "w") as fh:
        json.dump(manifest, fh, indent=1)
    print(f"manifest -> {mpath}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
