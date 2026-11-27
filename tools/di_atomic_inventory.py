#!/usr/bin/env python3
"""CK-3: extract every __atomic_* call site from dist_ingest.c (systematic
reconstruction). Emits a markdown table fragment. Not a full analyzer;
per-object synchronization analysis is in ATOMIC_SEMANTICS.md."""
import re, sys

SRC = sys.argv[1] if len(sys.argv) > 1 else "stage0/dist_ingest/dist_ingest.c"
pat = re.compile(r"__atomic_(store_n|load_n|fetch_add|fetch_sub|exchange|compare_exchange\w*|thread_fence)\s*\(([^;]*)", re.S)

def split_args(s):
    out, depth, cur = [], 0, ""
    for ch in s:
        if ch in "([":
            depth += 1; cur += ch
        elif ch in ")]":
            if depth == 0:
                break
            depth -= 1; cur += ch
        elif ch == "," and depth == 0:
            out.append(cur.strip()); cur = ""
        else:
            cur += ch
    if cur.strip():
        out.append(cur.strip())
    return out

def clean(x):
    return re.sub(r"\s+", " ", x).strip()

def main():
    src = open(SRC).read()
    lines = src.split("\n")
    rows = []
    for m in pat.finditer(src):
        op = m.group(1)
        args = split_args(m.group(2))
        line_no = src.count("\n", 0, m.start()) + 1
        # find enclosing function (rough)
        fn = "?"
        for i in range(line_no - 1, -1, -1):
            fm = re.match(r"(?:static\s+)?[A-Za-z_][\w\*\s]*?\b(\w+)\s*\([^;{}]*\)\s*\{?\s*$", lines[i].strip())
            if fm:
                fn = fm.group(1); break
        order = "?"
        obj = args[0] if args else "?"
        if op == "store_n" and len(args) >= 3:
            order = args[2]; 
        elif op == "load_n" and len(args) >= 2:
            order = args[1]
        elif op == "fetch_add" and len(args) >= 3:
            order = args[2]
        elif op in ("exchange",) and len(args) >= 3:
            order = args[2]
        order = clean(order).replace("__ATOMIC_", "")
        # strip order from obj display
        rows.append((line_no, op, clean(obj), order, fn, clean(m.group(0))[:110]))
    print("TOTAL __atomic_* call sites:", len(rows))
    print("")
    print("| # | line | op | object | order | enclosing fn |")
    print("|---|---|---|---|---|---|")
    for i, (ln, op, obj, order, fn, _raw) in enumerate(sorted(rows), 1):
        print("| %d | %d | %s | `%s` | %s | %s |" % (i, ln, op, obj.replace("|", "\\|"), order, fn))

if __name__ == "__main__":
    main()
