#!/usr/bin/env python3
"""Find repeated DECISIONS in the Python front end.

Duplicated FUNCTION bodies are the easy case. The expensive one is a
duplicated decision written out INLINE -- inside a function body, at
the point where the rule is applied -- which a function-level scan
does not see at all.

That distinction is not academic. D-PORT2/D6 established the rule
"a helper child's death is EXPECTED when an abort is already in
flight" and wired it into 2 of the 28 places the front end applies it;
the other 26 were inline. A scan that compared whole functions found
none of them.

This tool therefore compares BLOCKS -- a function body, and the body of
every if/for/while/try/with/except -- after canonicalising them:
names, attributes and literals are erased, keywords and operators are
kept, and nested function bodies are not descended into (so a closure
is not reported as a clone of the function that contains it).

Usage:
    tools/ssot_scan.py [root ...]        # default: python/forkrun
    tools/ssot_scan.py --min-copies N    # only groups with >= N copies
    tools/ssot_scan.py --min-chars N     # only groups whose canonical
                                         # form is at least N chars
"""

import argparse
import ast
import os
import sys
from collections import defaultdict


class Canon(ast.NodeTransformer):
    """Erase names, attributes and literals.

    Every visitor MUST return the node: NodeTransformer.generic_visit
    deletes the field when a visitor returns None, which silently
    strips the node's children.
    """

    def visit_Name(self, node):
        node.id = "_"
        return node

    def visit_Attribute(self, node):
        self.generic_visit(node)
        node.attr = "_"
        return node

    def visit_arg(self, node):
        node.arg = "_"
        return node

    def visit_Constant(self, node):
        node.value = "_"
        return node

    def visit_Global(self, node):
        node.names = ["_"]
        return node

    def visit_Nonlocal(self, node):
        node.names = ["_"]
        return node


def canon(stmts):
    """Canonical form of a statement list."""
    body = []
    for s in stmts:
        s = Canon().visit(s)
        if (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant)
                and isinstance(s.value.value, str)):
            continue          # a docstring
        body.append(s)
    if not body:
        return None
    return ast.dump(ast.Module(body=body, type_ignores=[]),
                    annotate_fields=False, include_attributes=False)


BLOCK_OWNERS = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.With,
                 ast.AsyncWith, ast.Try, ast.ExceptHandler)


def blocks_of(node):
    """Every statement block inside this scope, with its owner."""
    out = []
    for child in ast.walk(node):
        if isinstance(child, ast.Module):
            out.append((child.body, "module"))
        elif isinstance(child, BLOCK_OWNERS):
            out.append((child.body, type(child).__name__))
            if isinstance(child, ast.Try):
                for h in child.handlers:
                    out.append((h.body, "ExceptHandler"))
                out.append((child.finalbody, "finalbody"))
        elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.append((child.body, "def %s" % child.name))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("roots", nargs="*",
                    default=["/mnt/ramdisk/forkrun/python/forkrun"])
    ap.add_argument("--min-copies", type=int, default=2)
    ap.add_argument("--min-chars", type=int, default=400)
    args = ap.parse_args()

    groups = defaultdict(list)
    total = 0
    for root in args.roots:
        for dirpath, _d, files in os.walk(root):
            for fn in sorted(files):
                if not fn.endswith(".py"):
                    continue
                path = os.path.join(dirpath, fn)
                try:
                    src = open(path, encoding="utf-8").read()
                    tree = ast.parse(src)
                except (SyntaxError, UnicodeDecodeError):
                    continue
                for stmts, owner in blocks_of(tree):
                    if not stmts:
                        continue
                    total += 1
                    c = canon(stmts)
                    if c is None or len(c) < args.min_chars:
                        continue
                    groups[c].append((path, stmts[0].lineno, owner,
                                       len(stmts)))

    dupes = {k: v for k, v in groups.items() if len(v) >= args.min_copies}
    ranked = sorted(dupes.items(), key=lambda kv: (-len(kv[1]), -len(kv[0])))

    print("scanned %d blocks; %d repeated groups\n"
          % (total, len(ranked)))
    for c, places in ranked:
        print("%d copies, %d statements each:" % (len(places), places[0][3]))
        for path, line, owner, _n in places:
            print("    %s:%d  [%s]" % (path, line, owner))
        print()
    return 0 if ranked else 1


if __name__ == "__main__":
    sys.exit(main())
