# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) Virtastic
"""Fail when port-authored Python is unreachable.

    python tools/check-unreachable-fcweb.py <patched-tree>

Walks every function that carries an FCWEB comment and reports any statement that can
never run -- anything following a return, raise, break or continue in the same block.

WHY

This is the fourth time a fix in this port was written somewhere it could not execute:

  * an #ifdef FCWEB_REAL_CPYTHON that nothing defined,
  * a patch marker that matched any version, so a stale tree passed as patched,
  * a FEM symbol-dir guard keyed on empty when the value was wrong but not empty,
  * the gmsh bridge appended to update_properties(), which runs after the mesh is read.

The fourth had a twin found while fixing it. get_gmsh_command's wasm early-return had
been spliced into the middle of `if not self.gmsh_bin:`, so the rest of that branch --
the Darwin lookup, the "Gmsh binary not found" error, the assignment of gmsh_bin
itself -- sat after a return and could not run. Both compile. Both read as fixes. The
only thing that distinguishes them from working code is whether control reaches them.

Scoping this to functions containing an FCWEB comment keeps it to lines this port owns,
so it needs no baseline of upstream's own dead code to compare against.
"""
import ast
import io
import os
import sys

TERMINAL = (ast.Return, ast.Raise, ast.Break, ast.Continue)


def blocks(node):
    """Every statement list in the tree, so nested bodies are checked too."""
    for n in ast.walk(node):
        for field in ('body', 'orelse', 'finalbody'):
            b = getattr(n, field, None)
            if isinstance(b, list) and b and isinstance(b[0], ast.stmt):
                yield b


def check(path):
    try:
        src = io.open(path, encoding='utf-8').read()
    except (OSError, UnicodeDecodeError):
        return []
    if 'FCWEB' not in src:
        return []
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        return [(e.lineno or 0, 'does not parse: %s' % e.msg)]

    lines = src.split('\n')
    bad = []
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        span = lines[fn.lineno - 1:getattr(fn, 'end_lineno', fn.lineno)]
        if not any('FCWEB' in l for l in span):
            continue
        for body in blocks(fn):
            for i, stmt in enumerate(body[:-1]):
                if isinstance(stmt, TERMINAL):
                    nxt = body[i + 1]
                    bad.append((nxt.lineno,
                                'unreachable: %s at line %d cannot be followed by %s'
                                % (type(stmt).__name__.lower(), stmt.lineno,
                                   lines[nxt.lineno - 1].strip()[:60])))
                    break
    return bad


def main():
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    root = sys.argv[1]
    checked = failures = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in ('.git', 'build')]
        for name in filenames:
            if not name.endswith('.py'):
                continue
            path = os.path.join(dirpath, name)
            bad = check(path)
            if bad:
                checked += 1
            for lineno, msg in bad:
                failures += 1
                print('%s:%d: %s' % (os.path.relpath(path, root).replace(os.sep, '/'),
                                     lineno, msg))
    if failures:
        print('\n%d unreachable block(s) in port-authored Python' % failures)
        return 1
    print('no unreachable port-authored Python')
    return 0


if __name__ == '__main__':
    sys.exit(main())
