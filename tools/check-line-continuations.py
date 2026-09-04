# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) Virtastic
"""Catch a comment sitting inside a backslash-continued command.

    python tools/check-line-continuations.py

A shell line continuation cannot span a comment. Given

    emcmake cmake -S "$SRC" -B "$BUILD" \\
      -DCMAKE_C_FLAGS="..." \\
      # explaining the next flag
      -DCMAKE_CXX_FLAGS="..." \\

the shell ends the command at the comment and then tries to RUN the following line as a
command of its own. The result is exit 127, "-DCMAKE_CXX_FLAGS: command not found", from a
script that looks entirely reasonable.

`bash -n` does not catch this, which is the whole reason for this file: the text is
syntactically valid, it simply means something other than what it looks like. That is the
worst kind of shell bug, and it cost a four-minute CI run on the VTK configure before
anyone noticed the flag was never being passed.

The rule is narrow on purpose -- a comment is only a problem when the PREVIOUS
non-blank line ends in a backslash. A comment between commands is fine, and a comment
before a continued command is fine; both are normal and common in this tree.
"""
import io
import subprocess
import sys


def problems_in(path):
    try:
        text = io.open(path, encoding='utf-8', errors='replace').read()
    except OSError:
        return []
    found = []
    continued = False
    for lineno, raw in enumerate(text.split(chr(10)), 1):
        line = raw.rstrip(chr(13))
        stripped = line.strip()
        if continued and stripped.startswith('#'):
            found.append((lineno, stripped[:72]))
        # A blank line inside a continuation is already a syntax error bash WILL catch,
        # so only track non-blank lines here.
        if stripped:
            continued = line.rstrip().endswith(chr(92))
    return found


def main():
    listed = subprocess.check_output(['git', 'ls-files', '*.sh']).decode()
    bad = []
    for path in listed.split(chr(10)):
        if not path:
            continue
        for lineno, text in problems_in(path):
            bad.append((path, lineno, text))

    if bad:
        for path, lineno, text in bad:
            print('%s:%d: comment inside a line continuation -- the command ends here and '
                  'the next line runs as its own command' % (path, lineno), file=sys.stderr)
            print('    %s' % text, file=sys.stderr)
        print('', file=sys.stderr)
        print('%d broken continuation(s). bash -n cannot see these.' % len(bad),
              file=sys.stderr)
        return 1
    print('no comments inside line continuations')
    return 0


if __name__ == '__main__':
    sys.exit(main())
