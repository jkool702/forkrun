#!/usr/bin/env python3
"""Generate the Python interpreter compatibility matrix from the single
authoritative source: tools/wheel_matrix.py::SUPPORTED_MINORS.

Emits a JSON object suitable for GitHub Actions' `fromJson()`:
    {"include": [{"py": "3.10", "image": "ubuntu:22.04", "setup": "system"}, ...]}

Environment selection is kept SEPARATE from the supported-minor definition:
this script owns the mapping from a minor to a base image/setup, but the
SET of minors comes from SUPPORTED_MINORS only.

Usage:
    python3 tools/gen_python_matrix.py [--format json|lines]
"""
from __future__ import annotations

import argparse
import json
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "tools"))
import wheel_matrix  # noqa: E402

# Environment selection (NOT the support definition). Maps a minor to the
# Ubuntu image and setup method used to obtain that interpreter. Minors
# not listed here are unsupported for CI environment selection and the
# script fails loudly rather than silently dropping them.
_ENV = {
    "3.10": ("ubuntu:22.04", "system"),
    "3.11": ("ubuntu:22.04", "deadsnakes"),
    "3.12": ("ubuntu:24.04", "system"),
    "3.13": ("ubuntu:24.04", "deadsnakes"),
    "3.14": ("ubuntu:24.04", "deadsnakes"),
    "3.15": ("ubuntu:24.04", "deadsnakes"),
}


def build_matrix():
    include = []
    for minor in wheel_matrix.SUPPORTED_MINORS:
        if minor not in _ENV:
            raise SystemExit(
                "no CI environment mapping for supported minor %s; "
                "add it to _ENV in tools/gen_python_matrix.py" % minor)
        image, setup = _ENV[minor]
        include.append({"py": minor, "image": image, "setup": setup})
    return {"include": include}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--format", choices=("json", "lines"), default="json")
    args = ap.parse_args(argv)
    m = build_matrix()
    if args.format == "lines":
        for e in m["include"]:
            print("%s %s %s" % (e["py"], e["image"], e["setup"]))
    else:
        print(json.dumps(m))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())