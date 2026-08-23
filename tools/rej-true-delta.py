#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) Virtastic
"""Extract the REAL change out of a whole-file patch hunk.

patches/freecad.patch stores nine files as a single hunk covering the entire file -- 3,538
lines for src/App/Application.cpp alone. That is how the patch was captured, not how big the
edit is: a whole-file hunk contains the original on the '-' side and the modified version on
the '+' side, so the actual delta can be recovered by diffing the two halves against each
other.

This matters when rebasing onto a new FreeCAD release. A whole-file hunk can never apply
once upstream touches the file, and reading 3,538 lines of context to find the change is
hopeless. Recovering the delta turns each one into a handful of lines to re-apply.

    python3 tools/rej-true-delta.py <file.rej>

Prints a normal unified diff of what the patch actually changes.
"""
import difflib
import sys


def halves(path):
    """Reconstruct the two sides of a .rej hunk."""
    old, new = [], []
    for line in open(path, encoding='utf-8', errors='replace'):
        line = line.rstrip('\n')
        if line.startswith(('---', '+++', '@@')):
            continue
        if line.startswith('-'):
            old.append(line[1:])
        elif line.startswith('+'):
            new.append(line[1:])
        elif line.startswith(' '):
            old.append(line[1:])
            new.append(line[1:])
        elif line.startswith('\\'):
            continue
        else:                      # a bare line is context in some emitters
            old.append(line)
            new.append(line)
    return old, new


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    for path in sys.argv[1:]:
        old, new = halves(path)
        diff = list(difflib.unified_diff(old, new, fromfile='as-shipped-by-upstream',
                                         tofile='as-this-port-wants-it', lineterm='', n=3))
        changed = sum(1 for d in diff if d.startswith(('+', '-'))
                      and not d.startswith(('+++', '---')))
        print('=' * 78)
        print('%s   (%d lines in hunk -> %d lines actually changed)'
              % (path, len(old), changed))
        print('=' * 78)
        for d in diff:
            print(d)
        print()
    return 0


if __name__ == '__main__':
    sys.exit(main())
