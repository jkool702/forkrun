"""Stage 0 corpus generator (campaign spec §3 corpus identity).

Deterministic, seeded, JSONL-style records matching the ml pipeline's
light/medium(/heavy) shapes — corpus identity is recorded so baseline
and rental runs are byte-identical.

Usage:
  make_corpus.py --records 5000000 --variant light --out stage0/corpus/light_5m.txt
"""

import argparse
import hashlib
import json
import os
import random
import string

VARIANTS = ("light", "medium", "heavy")


def _gen(path, records, variant):
    h = hashlib.sha256()
    rng = random.Random(42)
    n = 0
    with open(path, "w", encoding="utf-8") as fh:
        for i in range(records):
            if variant == "light":
                rec = {"id": i, "text": "".join(
                    rng.choice(string.ascii_lowercase) for _ in range(80)),
                    "ts": 1700000000 + i}
            elif variant == "medium":
                rec = {"id": i,
                       "text": "".join(
                           rng.choice(string.ascii_lowercase + " ")
                           for _ in range(340)),
                       "ts": 1700000000 + i,
                       "user": "u%d" % (i % 1000)}
            else:
                rec = {"id": i,
                       "text": "".join(
                           rng.choice(string.ascii_lowercase + " ")
                           for _ in range(1300)),
                       "ts": 1700000000 + i,
                       "user": "u%d" % (i % 1000),
                       "meta": {"depth": rng.random(),
                                "tags": ["t%d" % j for j in range(6)]}}
            line = json.dumps(rec, separators=(",", ":")) + "\n"
            fh.write(line)
            h.update(line.encode())
            n += 1
    return n, h.hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--records", type=int, required=True)
    ap.add_argument("--variant", choices=VARIANTS, required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    n, digest = _gen(args.out, args.records, args.variant)
    size = os.path.getsize(args.out)
    with open(args.out + ".manifest.json", "w", encoding="utf-8") as fh:
        json.dump({"variant": args.variant, "records": n,
                   "bytes": size, "sha256": digest,
                   "seed": 42, "path": args.out},
                  fh, indent=2, sort_keys=True)
    print("%s: %d records, %d bytes, sha256=%s" % (
        args.out, n, size, digest[:16]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
