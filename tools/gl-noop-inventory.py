#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) Virtastic
"""Count and name the entry points in gl_legacy_stubs.c that still do nothing.

That file exists to DEFINE the fixed-function GL symbols emscripten's LEGACY_GL_EMULATION
lacks, so Coin and FreeCAD link at all. An entry point whose body is empty is not
"unimplemented" at run time -- it is a draw, a state change or a query silently thrown away,
which is why this number is worth watching. It should only ever fall.

Three categories, because lumping them together misleads:

  EMPTY        the body is nothing but `(void)arg;` casts. A silent wrong answer.
  CONSTANT     returns a fixed value on purpose -- glRenderMode returning 0 means "no
               selection hits", and glGenLists returning 0 means "no display lists", which
               is what makes Coin fall back to immediate mode.
  FORWARDING   actually does something: calls the real emulation entry point, or implements
               the call in terms of ones that exist.

Anchored on the function definition. A first version of this counted a continuation line of
glBitmap's multi-line body as an entry point, and filed glRenderMode with the empty ones.

    python3 tools/gl-noop-inventory.py [path]     # default: gl_legacy_stubs.c
"""
import re
import sys

DEFN = re.compile(r'^(?:void|GLint|GLuint) (gl[A-Za-z0-9]+)\((.*)\)\s*\{(.*)\}\s*$')
VOID_CAST = re.compile(r'\(void\)[A-Za-z0-9_]+\s*;')
RETURN_CONST = re.compile(r'return [^;]+;')


def classify(path):
    empty, constant, forwarding = [], [], []
    for line in open(path, encoding='utf-8'):
        m = DEFN.match(line.rstrip('\n'))
        if not m:
            continue
        name, body = m.group(1), m.group(3).strip()
        stripped = VOID_CAST.sub('', body).strip()
        if not stripped:
            empty.append(name)
        elif RETURN_CONST.fullmatch(stripped):
            constant.append(name)
        else:
            forwarding.append(name)
    return empty, constant, forwarding


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else 'gl_legacy_stubs.c'
    empty, constant, forwarding = classify(path)
    total = len(empty) + len(constant) + len(forwarding)
    print('  %s: %d single-line entry points' % (path, total))
    print('    EMPTY (silently drop the call) : %d' % len(empty))
    print('    CONSTANT (deliberate answer)   : %d  %s' % (len(constant), ', '.join(constant)))
    print('    FORWARDING (real work)         : %d  %s' % (len(forwarding), ', '.join(forwarding)))
    print()
    print('  --- the empty ones, so this is reviewable rather than a number ---')
    for n in empty:
        print('    ' + n)
    return 0


if __name__ == '__main__':
    sys.exit(main())
