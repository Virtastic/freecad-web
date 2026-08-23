"""Stamp SPDX-License-Identifier headers on the files this repository authors.

    python tools/add-spdx-headers.py [--check]

LGPL compliance is not only the LICENSE file: each source file should say what it is
licensed under, so a file that travels alone (a build script someone copies, a patch
tool vendored elsewhere) carries its terms with it. Idempotent -- files that already
carry an SPDX tag are left alone. --check exits non-zero if anything is unstamped,
which is what CI runs.

Skips: vendored third-party files (qtloader.js is The Qt Company's and keeps its own
header), generated output, dependency trees, and the patch files themselves (a patch's
content is upstream's, under upstream's terms).
"""
import io
import os
import sys

TAG = 'SPDX-License-Identifier: LGPL-2.1-or-later'
COPY = 'Copyright (c) Virtastic'

# extension -> (comment prefix, needs-shebang-awareness)
STYLES = {
    '.sh': '#',
    '.py': '#',
    '.js': '//',
    '.mjs': '//',
    '.css': None,      # /* */ block
    '.html': None,     # <!-- --> block
    '.yml': '#',
    '.yaml': '#',
}

SKIP_DIRS = {
    '.git', 'node_modules', 'deps', 'build', 'dist', 'LICENSES',
    'build-artifact-serve', 'patches', '__pycache__', 'src',
    # one-off forensic scripts, never distributed and never part of a build
    'scratchpad',
}
SKIP_FILES = {
    'qtloader.js',          # The Qt Company, LicenseRef-Qt-Commercial OR GPL-3.0-only
}


def header_for(path):
    ext = os.path.splitext(path)[1]
    if ext == '.html':
        return '<!-- %s -->\n<!-- %s -->\n' % (TAG, COPY)
    if ext == '.css':
        return '/* %s */\n/* %s */\n' % (TAG, COPY)
    pre = STYLES.get(ext)
    if not pre:
        return None
    return '%s %s\n%s %s\n' % (pre, TAG, pre, COPY)


def stamp(path, check):
    try:
        text = io.open(path, encoding='utf-8').read()
    except (UnicodeDecodeError, OSError):
        return None
    if 'SPDX-License-Identifier' in text[:2000]:
        return None
    head = header_for(path)
    if head is None:
        return None
    if check:
        return path
    lines = text.split('\n')
    at = 0
    # keep a shebang, an XML declaration or a doctype first -- inserting above them breaks the file
    if lines and (lines[0].startswith('#!') or lines[0].startswith('<?xml')
                  or lines[0][:9].lower() == '<!doctype'):
        at = 1
    out = '\n'.join(lines[:at]) + ('\n' if at else '') + head + '\n'.join(lines[at:])
    io.open(path, 'w', encoding='utf-8', newline='').write(out)
    return path


def main():
    check = '--check' in sys.argv
    root = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
    os.chdir(root)
    touched = []
    for dirpath, dirnames, filenames in os.walk('.'):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            if name in SKIP_FILES:
                continue
            p = os.path.normpath(os.path.join(dirpath, name))
            r = stamp(p, check)
            if r:
                touched.append(r)
    if check:
        if touched:
            print('%d file(s) missing an SPDX header:' % len(touched))
            for t in touched[:40]:
                print('   ' + t)
            return 1
        print('every source file carries an SPDX header')
        return 0
    print('stamped %d file(s)' % len(touched))
    for t in touched:
        print('   ' + t)
    return 0


if __name__ == '__main__':
    sys.exit(main())
