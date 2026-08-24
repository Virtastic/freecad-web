# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) Virtastic
"""Catch shell mangling in workflow run blocks before a two-hour job dies on it.

    python tools/check-run-block-escapes.py

A backslash-n that reaches a run block as two literal characters is not a newline: bash
drops the backslash and passes a bare `n` as an argument. That is exactly how the first
CI run of the boot gate died -- after two hours of compiling -- with

    boot-gate.py: error: unrecognized arguments: n

It happens when a YAML file is edited by a script whose own escaping is off by one layer,
which is easy to do and invisible in review, because `\\n` in a shell command looks
deliberate. The failure is also maximally expensive: it surfaces at the END of the longest
job in the pipeline.

It deliberately does NOT flag a backslash before a CRLF. Git stores these files LF and
checks them out LF on Linux, so a CRLF here is an artefact of a Windows working copy --
flagging it would fire on every legitimate multi-line command in the repository.
"""
import glob
import io
import sys


def main():
    problems = []
    for path in sorted(glob.glob('.github/workflows/*.yml')):
        raw = io.open(path, 'rb').read()
        crlf = b'\r\n' in raw
        for n, line in enumerate(raw.split(b'\n'), 1):
            bare = line.rstrip(b'\r')
            # A literal backslash-n inside a command line.
            if b'\\n' in bare and not bare.lstrip().startswith(b'#'):
                # printf/echo/sed legitimately use \n inside quotes; flag only the case
                # that reaches argv -- a backslash-n surrounded by whitespace.
                for token in bare.split():
                    if token == b'\\n':
                        problems.append((path, n, 'a bare backslash-n is passed as the '
                                                  'argument "n", not a newline'))
                        break
            # A backslash before a CRLF would escape the carriage return rather than
            # continue the line -- but only if the file reached the runner that way. Git
            # stores these LF and checks them out LF on Linux; the CRLF is an artefact of a
            # Windows working copy, so flagging it here is a false alarm on every
            # legitimate multi-line command in the file.

    if problems:
        for path, n, why in problems:
            print('::error file=%s,line=%d::%s' % (path, n, why))
        print('\n%d problem(s). These break the shell in ways that only show up when the '
              'job runs, which for the link job is two hours in.' % len(problems),
              file=sys.stderr)
        return 1

    print('  ok    no mangled escapes in any workflow run block')
    return 0


if __name__ == '__main__':
    sys.exit(main())
