#!/usr/bin/env python3
"""Stage 0 incumbent: tokenize-to-tensor via PyTorch DataLoader.

Primary incumbent per the work order. If torch (or tensorflow) is not
importable on this machine, the script emits an UNMEASURED row with the
reason instead of failing — the harness records it, the report explains.

Usage: tokenize_torch_loader.py TOKENS_I32 OUT [--workers N]
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bench_common import emit_unmeasured, now


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("output")
    ap.add_argument("--workers", type=int, default=0)
    args = ap.parse_args()
    try:
        import torch  # noqa: F401
        from torch.utils.data import DataLoader, TensorDataset
    except ImportError:
        try:
            import tensorflow  # noqa: F401
            emit_unmeasured("tokenize-to-tensor", "tensorflow.data",
                            "tensorflow present but no DataLoader leg written; torch absent")
        except ImportError:
            emit_unmeasured("tokenize-to-tensor", "torch-dataloader",
                            "neither torch nor tensorflow importable on this machine")
        return 0
    # If torch ever becomes available, the leg below is the intended shape;
    # until then it is untested scaffolding (kept minimal on purpose).
    t0 = now()
    import numpy as np
    toks = np.fromfile(args.input, dtype=np.int32)
    ds = TensorDataset(torch.from_numpy(toks.copy()))
    total = 0
    for batch in DataLoader(ds, batch_size=65536,
                            num_workers=args.workers or os.cpu_count()):
        total += int(batch[0].sum())
    with open(args.output, "w") as fh:
        fh.write(str(total) + "\n")
    from bench_common import Hasher, emit
    h = Hasher()
    h.update(str(total).encode())
    emit("tokenize-to-tensor", "torch-dataloader",
         os.path.getsize(args.input), now() - t0, h.hexdigest())
    return 0


if __name__ == "__main__":
    sys.exit(main())
