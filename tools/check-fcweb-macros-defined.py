# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) Virtastic
"""Every FCWEB_* macro the port tests must be defined somewhere.

    python tools/check-fcweb-macros-defined.py <patched-tree>

Collects the FCWEB_* macros used in #ifdef / #if defined() / #ifndef across the patched
tree, and requires each to be defined by a #define in the tree or by a -D flag in one of
this repository's build scripts.

WHY

The 1.1.3 port could not start at all, for months, with every gate green. The fix had been
written in an earlier session and sat behind

    #ifdef FCWEB_REAL_CPYTHON

a macro defined nowhere in this repository. It compiled. It read like a fix. It was never
once included in a build. A guard that can go quiet is not a guard, and the same is true of
a fix that can go quiet.

An #ifdef on an undefined macro is not always a bug -- it is the normal way to write an
opt-in. What makes it one here is the FCWEB_ prefix: these are the port's own switches, and
a port switch that nothing turns on is dead code wearing a fix's clothes.
"""
import io
import os
import re
import sys

USE = re.compile(r'#\s*(?:ifdef|ifndef)\s+(FCWEB_\w+)|defined\s*\(\s*(FCWEB_\w+)\s*\)')
DEFINE = re.compile(r'#\s*define\s+(FCWEB_\w+)')
DFLAG = re.compile(r'-D\s*(FCWEB_\w+)')

SOURCE_EXT = ('.c', '.cc', '.cpp', '.cxx', '.h', '.hh', '.hpp', '.hxx', '.inl')
SCRIPT_EXT = ('.sh', '.yml', '.yaml', '.txt', '.cmake', '.in')


def scan(root):
    used, defined = {}, set()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in ('.git', 'build', '__pycache__')]
        for name in filenames:
            if not name.endswith(SOURCE_EXT):
                continue
            path = os.path.join(dirpath, name)
            try:
                text = io.open(path, encoding='utf-8', errors='replace').read()
            except OSError:
                continue
            if 'FCWEB_' not in text:
                continue
            for m in DEFINE.finditer(text):
                defined.add(m.group(1))
            for i, line in enumerate(text.split('\n'), 1):
                for m in USE.finditer(line):
                    macro = m.group(1) or m.group(2)
                    used.setdefault(macro, (os.path.relpath(path, root).replace(os.sep, '/'), i))
    return used, defined


def from_build_scripts(here):
    """Macros this repository passes with -D, wherever it does it."""
    defined = set()
    for dirpath, dirnames, filenames in os.walk(here):
        dirnames[:] = [d for d in dirnames
                       if d not in ('.git', 'deps', 'build', 'node_modules', 'scratchpad',
                                    '__pycache__')]
        for name in filenames:
            if not (name.endswith(SCRIPT_EXT) or name.endswith(SOURCE_EXT)
                    or name == 'CMakeLists.txt'):
                continue
            try:
                text = io.open(os.path.join(dirpath, name),
                               encoding='utf-8', errors='replace').read()
            except OSError:
                continue
            if 'FCWEB_' not in text:
                continue
            for m in DFLAG.finditer(text):
                defined.add(m.group(1))
            for m in DEFINE.finditer(text):
                defined.add(m.group(1))
    return defined


def main():
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    root = sys.argv[1]
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    used, defined = scan(root)
    defined |= from_build_scripts(here)

    rc = 0
    for macro in sorted(used):
        if macro not in defined:
            path, line = used[macro]
            print('::error::%s:%d: %s is tested but never defined -- by a #define in the '
                  'tree or a -D in any build script. Everything it guards is dead code.'
                  % (path, line, macro))
            rc = 1
    if rc == 0:
        print('  ok    every FCWEB_* macro tested is defined somewhere (%d)' % len(used))
    return rc


if __name__ == '__main__':
    sys.exit(main())
