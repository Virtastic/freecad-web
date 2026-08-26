# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) Virtastic
"""Find build steps whose failure cannot be seen, because a pipe ate the exit status.

    python tools/check-pipeline-status.py .github/workflows/*.yml

In a shell, `a | tee log` exits with tee's status, not a's. tee always succeeds. So

    bash link.sh 2>&1 | tee link.txt | tail -40
    rc=$?

sets rc to 0 no matter how badly link.sh failed -- and `set -e` never sees it either.

This is not hypothetical. Run 32868637104 ended its Link step with

    wasm-ld: error: MainGui.cpp.o: undefined symbol: PyInit_QtSvg
    em++: error: '.../wasm-ld ...' failed (returned 1)

and GitHub recorded "Link: success". The step handed on the PREVIOUS bin/FreeCAD.{js,wasm,data}
from an abandoned experiment. That artifact was released, deployed, and served to users for
two days with no numpy, matplotlib, PIL or ifcopenshell -- FEM, the Addon Manager and Draft
all dead, while the app booted in 13 s and drew a box perfectly.

The fix is `rc=${PIPESTATUS[0]}`. This checks that every build pipeline uses it, because
the failing form and the working form differ by nine characters and read identically at a
glance. Worse, `rc=$?` immediately after the pipeline LOOKS like a guard -- which is how
one survived review in a second lane after the first was fixed.
"""
import glob
import io
import os
import re
import sys

# Commands whose failure must not be swallowed. Version banners are excluded below.
BUILD = re.compile(r'\b(bash|sh|ninja|cmake|make|emcc|em\+\+|emconfigure|emmake|python3?)\b')
PIPED = re.compile(r'\|\s*(tee|tail|head|grep)\b')
# `foo --version | head -1` is a banner, not a build step.
BANNER = re.compile(r'--version|-V\b')


def check(path):
    lines = io.open(path, encoding='utf-8', errors='replace').read().split('\n')
    bad = []
    for i, line in enumerate(lines):
        s = line.strip()
        if s.startswith('#') or not PIPED.search(s):
            continue
        # The command may be many lines above: a cmake invocation with twenty -D flags ends
        # in a bare "2>&1 | tee log" continuation line. Walk back over backslash
        # continuations to find what is actually being run. The first version of this check
        # looked only at the piped line and therefore MISSED the exact case that motivated
        # it -- build-freecad.yml's configure, which is the one that reads rc=$?.
        head, k = s, i
        while k > 0 and lines[k - 1].rstrip().endswith(chr(92)):
            k -= 1
            head = lines[k].strip() + ' ' + head
        if not BUILD.search(head) or BANNER.search(head):
            continue
        # An assignment from a command substitution -- hdr="$(grep ... | head -1)" -- is
        # reading a value, not running a build, and its failure shows up as an empty value.
        if re.match(r'^[A-Za-z_][A-Za-z0-9_]*=.*\$\(', s):
            continue
        # Look ahead past comments and blank lines for a status read.
        window, j = [], i + 1
        while j < len(lines) and len(window) < 4:
            nxt = lines[j].strip()
            j += 1
            if not nxt or nxt.startswith('#'):
                continue
            window.append(nxt)
        joined = ' '.join(window)
        if 'PIPESTATUS' in joined:
            continue
        why = ('reads $? , which is the PIPE status and is always 0 here'
               if re.search(r'\brc=\$\?|\bif\s+\[\s+"?\$\?', joined)
               else 'never checks the status at all')
        bad.append((i + 1, s[:100], why))
    return bad


def main():
    args = sys.argv[1:] or glob.glob(os.path.join('.github', 'workflows', '*.yml'))
    paths = []
    for a in args:
        paths.extend(glob.glob(a) if any(c in a for c in '*?[') else [a])

    total = 0
    for p in sorted(set(paths)):
        for ln, text, why in check(p):
            total += 1
            print('::error::%s:%d a build pipeline %s' % (p, ln, why))
            print('    %s' % text)
    if total:
        print('')
        print('%d pipeline(s) can report success while the build failed. Use '
              'rc=${PIPESTATUS[0]} immediately after the pipeline and act on it.' % total,
              file=sys.stderr)
        return 1
    print('every build pipeline checks PIPESTATUS (%d workflow file(s))' % len(set(paths)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
