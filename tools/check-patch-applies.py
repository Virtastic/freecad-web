# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) Virtastic
"""Check a unified diff against a source tree byte for byte, the way GNU patch does.

    python tools/check-patch-applies.py patches/freecad.patch deps/src/freecad

Why this exists rather than just running patch(1): the two implementations disagree. GNU
patch 2.8 on Linux compares a hunk's context lines to the file BYTE FOR BYTE and rejects
the hunk with "different line endings" if they differ; the msys patch(1) on the machine
where this port is generated silently tolerates the mismatch. So the tolerant tool cannot
be the one that decides whether the patch is correct, and "it applies here" is not
evidence about CI.

That is not hypothetical. patches/freecad.patch was generated with `diff
--strip-trailing-cr`, which made every context line LF -- while 33 of the 80 files it
touches are CRLF in FreeCAD 1.1.3. It applied cleanly on Windows and failed every hunk of
those 33 files on Linux.

Exits non-zero and names the first mismatching line of each failing hunk.
"""
import io, os, sys

patch_path, tree = sys.argv[1], sys.argv[2]
raw = io.open(patch_path, 'rb').read().decode('utf-8', 'replace')
lines = raw.split('\n')

i, problems, checked, hunks = 0, [], 0, 0
cur = None
while i < len(lines):
    l = lines[i]
    if l.startswith('--- a/'):
        cur = l[6:].strip().split('\t')[0]
        i += 1; continue
    if l.startswith('@@') and cur:
        hunks += 1
        head = l.split('@@')[1].strip()          # -start,count +start,count
        old = head.split()[0]                    # -start,count
        start = int(old[1:].split(',')[0])
        i += 1
        want = []
        while i < len(lines) and not lines[i].startswith(('@@', '--- ', 'diff ')):
            t = lines[i]
            if t.startswith((' ', '-')):
                want.append(t[1:])
            elif not t.startswith(('+', chr(92))):
                break
            i += 1
        p = os.path.join(tree, cur)
        if not os.path.exists(p):
            if start != 0:
                problems.append('%s: missing from tree' % cur)
            continue
        body = io.open(p, 'rb').read().decode('utf-8', 'replace')
        # split keeping the exact terminator, so CR survives into the comparison
        src = body.split('\n')
        seg = src[start - 1:start - 1 + len(want)] if start > 0 else []
        checked += len(want)
        if seg != want:
            for n, (a, b) in enumerate(zip(want, seg)):
                if a != b:
                    problems.append('%s:%d\n      patch: %r\n      tree : %r'
                                    % (cur, start + n, a[-40:], b[-40:]))
                    break
            else:
                problems.append('%s: hunk at %d is longer than the file' % (cur, start))
        continue
    i += 1

print('%d hunks, %d context/removed lines compared byte for byte' % (hunks, checked))
if problems:
    print('\n%d MISMATCH(ES):' % len(problems))
    for p in problems[:15]:
        print('  ' + p)
    sys.exit(1)
print('every hunk matches the tree exactly')
