# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) Virtastic
"""Fail when port-authored Python cannot run.

    python tools/check-unreachable-fcweb.py <patched-tree>

Three ways a fix can be present and still never execute, all of them found in this port:

  * unreachable  -- a statement after a return/raise/break/continue in the same block,
  * shadowed     -- a def that a later def of the same name in the same scope replaces,
  * stringified  -- code pasted inside a docstring, where it is prose.

WHY

Every one of these compiles. Every one reads like a fix in review. The only thing that
separates them from working code is whether control reaches them, and that is not
something a reader reliably checks:

  * an #ifdef FCWEB_REAL_CPYTHON that nothing defined,
  * a patch marker that matched any version, so a stale tree passed as patched,
  * a FEM symbol-dir guard keyed on empty when the value was wrong but not empty,
  * the gmsh bridge appended to update_properties(), which runs after the mesh is read,
  * get_gmsh_command's wasm early-return spliced into the middle of `if not
    self.gmsh_bin:`, leaving the rest of that branch after a return,
  * _FcwebGmshProcess.waitForFinished, shadowed by an older one-line stub further down
    the same class that returned True unconditionally -- so the blocking mesh path
    reported success without meshing,
  * setup_ccx's wasm early-return pasted INSIDE the method docstring, so every browser
    solve raised "CalculiX binary not found" from the binary search below it.

Scoping the checks to files and scopes carrying FCWEB keeps them to lines this port owns,
so no baseline of upstream's own dead code is needed to compare against.
"""
import ast
import io
import os
import re
import sys

TERMINAL = (ast.Return, ast.Raise, ast.Break, ast.Continue)

CODE_LINE = re.compile(r'^[ \t]*(if|for|while|return|raise|import|from|try|with|def|class)\b')


def blocks(node):
    """Every statement list in the tree, so nested bodies are checked too."""
    for n in ast.walk(node):
        for field in ('body', 'orelse', 'finalbody'):
            b = getattr(n, field, None)
            if isinstance(b, list) and b and isinstance(b[0], ast.stmt):
                yield b


def scope_defs(node):
    """Names bound by def directly in this class or module body."""
    seen = {}
    for stmt in getattr(node, 'body', []):
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            seen.setdefault(stmt.name, []).append(stmt)
    return seen


def stringified(tree):
    """Port code pasted into a string literal, where it parses as prose."""
    bad = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        text = node.value
        if '_fcweb' not in text and 'FCWEB' not in text:
            continue
        body = [l for l in text.split('\n') if CODE_LINE.match(l)]
        if body:
            bad.append((node.lineno,
                        'stringified: this is inside a string literal, not code: %s'
                        % body[0].strip()[:70]))
    return bad


def shadowed(tree):
    """A def that a later def of the same name in the same scope replaces."""
    bad = []
    scopes = [tree] + [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
    for scope in scopes:
        for name, defs in scope_defs(scope).items():
            if len(defs) < 2:
                continue
            # No FCWEB gate on the span: the shadowing stub that cost this port a
            # working mesher carried no marker of its own, and two defs of one name in
            # one scope are a bug wherever they come from.
            last = defs[-1]
            bad.append((defs[0].lineno,
                        'shadowed: %s is defined again at line %d, so this one never runs'
                        % (name, last.lineno)))
    return bad


def unreachable(tree, lines):
    """A statement that follows a return, raise, break or continue in the same block."""
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


def check(path):
    try:
        src = io.open(path, encoding='utf-8').read()
    except (OSError, UnicodeDecodeError):
        return []
    if 'FCWEB' not in src and '_fcweb' not in src:
        return []
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        return [(e.lineno or 0, 'does not parse: %s' % e.msg)]

    lines = src.split('\n')
    return sorted(stringified(tree) + shadowed(tree) + unreachable(tree, lines))


def main():
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    root = sys.argv[1]
    failures = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in ('.git', 'build', '__pycache__')]
        for name in sorted(filenames):
            if not name.endswith('.py'):
                continue
            path = os.path.join(dirpath, name)
            for lineno, msg in check(path):
                failures += 1
                print('%s:%d: %s' % (os.path.relpath(path, root).replace(os.sep, '/'),
                                     lineno, msg))
    if failures:
        print('\n%d block(s) of port-authored Python that cannot run' % failures)
        return 1
    print('all port-authored Python is reachable')
    return 0


if __name__ == '__main__':
    sys.exit(main())
