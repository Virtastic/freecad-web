#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) Virtastic
"""Every `const X_PY = [...].join("\\n")` block in play-gui/freecad-gui.html is Python source
that the page dispatches into the embedded interpreter.

A syntax error in one of those is invisible: the page still loads, the dispatch still runs,
and the interpreter raises somewhere nobody is looking -- the startup step simply never
happens. That is how a Report-view close and a window-geometry fix both silently did nothing
until each was traced by hand.

Nothing else compiles these. A JS linter sees string literals; a Python linter never opens
the HTML. So compile them here, and let ci.yml fail the build instead of a user finding it.

    python3 tools/check-page-python.py
"""
import io
import json
import re
import sys

PAGE = 'play-gui/freecad-gui.html'
BS = chr(92)
# const NAME_PY = [ "line", "line", ... ].join("\n");
BLOCK = re.compile(r'const (' + r'\w+' + r'_PY)\s*=\s*\[(.*?)\]\.join\("' + BS + BS + r'n"\);', re.S)
# One element per line, exactly as the page writes them: a double-quoted JS string and a comma.
# JS and JSON agree on this subset, so json.loads gives the real characters -- including the
# difference between an escaped newline and a literal one, which is the bug this catches.
ELEMENT = re.compile(r'^\s*("(?:[^"' + BS + BS + r']|' + BS + BS + r'.)*")\s*,\s*$', re.M)


def main():
    text = io.open(PAGE, encoding='utf-8').read()
    blocks = list(BLOCK.finditer(text))
    if not blocks:
        print('::error::%s has no `const X_PY = [...].join()` blocks -- the pattern moved, '
              'and this check is now watching nothing. Fix the pattern.' % PAGE)
        return 1

    rc = 0
    for match in blocks:
        name, body = match.group(1), match.group(2)
        lines = [json.loads(m.group(1)) for m in ELEMENT.finditer(body)]
        code = '\n'.join(lines)
        try:
            compile(code, name, 'exec')
        except SyntaxError as exc:
            rc = 1
            print('::error::%s in %s does not compile: line %s: %s'
                  % (name, PAGE, exc.lineno, exc.msg))
            for i, line in enumerate(code.split('\n'), 1):
                print('   %2d | %s' % (i, line))
            continue
        print('  ok  %-10s %2d lines' % (name, len(lines)))
    return rc


if __name__ == '__main__':
    sys.exit(main())
