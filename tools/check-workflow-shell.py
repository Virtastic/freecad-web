# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) Virtastic
"""Every workflow `run:` block must be valid shell.

    python tools/check-workflow-shell.py

A run block is a shell script that nothing ever parses until the runner executes it. Edit
one badly and the workflow still has valid YAML, the push still succeeds, the job still
starts -- and then dies on

    .../b629692e.sh: line 6: syntax error near unexpected token `else'

after the runner has already spent minutes checking out, restoring caches and installing a
toolchain. In the Qt lane that failure came several steps before the one being debugged,
which made it look like a regression in an unrelated place.

That is exactly how it happened: removing a block from a step cut at the first `fi`, which
belonged to a NESTED if, and left a dangling `else`/`fi` behind. The YAML was fine. The
diff looked fine. Only bash disagreed, and only on the runner.

Extracting each block and running `bash -n` over it costs milliseconds and catches the
whole class. It cannot catch a comment inside a line continuation -- that IS valid shell --
so tools/check-line-continuations.py covers the other half.
"""
import glob
import io
import os
import subprocess
import sys


def main():
    try:
        import yaml
    except ImportError:
        print('PyYAML not available; skipping', file=sys.stderr)
        return 0

    # Written inside the repo rather than the system temp dir: on Windows the shell is Git
    # Bash, which cannot open a native C:\... path handed to it as an argument.
    tmpdir = os.path.join('.git', 'shellcheck-tmp')
    os.makedirs(tmpdir, exist_ok=True)
    # PID in the name: two concurrent invocations sharing one path race, and the loser
    # reads a half-written file and reports a bogus syntax error ("No data available").
    # Seen for real while negative-testing this very checker against a background run.
    script = os.path.join(tmpdir, 'block-%d.sh' % os.getpid())

    problems = []
    checked = 0
    for wf in sorted(glob.glob('.github/workflows/*.yml')):
        doc = yaml.safe_load(io.open(wf, encoding='utf-8').read())
        for job in (doc.get('jobs') or {}).values():
            for step in (job.get('steps') or []):
                body = step.get('run')
                if not body:
                    continue
                checked += 1
                io.open(script, 'w', newline=chr(10)).write(body)
                proc = subprocess.run(['bash', '-n', script.replace(os.sep, '/')],
                                      capture_output=True, text=True)
                if proc.returncode:
                    first = (proc.stderr.strip().split(chr(10)) or [''])[0]
                    problems.append((wf, step.get('name') or '?', first))

    try:
        os.unlink(script)
    except OSError:
        pass

    if problems:
        for wf, name, err in problems:
            print('%s: step %r is not valid shell' % (wf, name), file=sys.stderr)
            print('    %s' % err, file=sys.stderr)
        print('', file=sys.stderr)
        print('%d of %d run block(s) would die on the runner.'
              % (len(problems), checked), file=sys.stderr)
        return 1
    print('all %d workflow run blocks are valid shell' % checked)
    return 0


if __name__ == '__main__':
    sys.exit(main())
