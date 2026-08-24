# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) Virtastic
"""Is THIS patch really in that tree? Check the content, not a stamp beside it.

    python tools/verify-patch-applied.py deps/src/pyside-setup patches/pyside-setup.patch
    python tools/verify-patch-applied.py <tree> <patch> --sample 6 --quiet

Exit 0 when every sampled added line is present in the tree, 1 when the tree is missing
lines the patch adds (stale or partially applied), 2 when the inputs are unusable.

WHY THIS EXISTS

Twice now this project has been burned by a marker that says "patched" while the tree
holds a different version of the patch. First `patches/apply.sh` skipped on a marker
string that matched ANY version of the patch, so CI built green around a source tree
missing the fix that made the application start at all. That was fixed by stamping each
tree with the patch's sha256 -- and then the stamp itself went wrong: a run reported
"pyside-setup: already applied (marker + hash)" for a tree whose bufferprocs_py37.cpp
plainly lacked the lines the current patch adds, and the build failed on exactly those
missing lines.

The pattern is the same both times: a piece of metadata standing in for the artifact.
A stamp is a claim about a tree; the tree is the fact. So this reads the patch, picks
lines it ADDS, and greps the tree for them. It cannot be fooled by a stale stamp,
because it never looks at one.

Sampling rather than a full diff is deliberate: a whole-tree diff would need the
pristine source, which is precisely what a self-hosted runner does not keep. A handful
of distinctive added lines per file is enough to separate "this patch is in" from
"some other version is in" -- the two states that matter.
"""
import argparse
import io
import os
import re
import sys

# Lines too short or too generic to identify a version of a patch.
BORING = re.compile(r'^[\s{}()\[\];]*$|^\s*(#endif|#else|\*/|//|/\*|\*)\s*$')


def added_lines(patch_path):
    """{path -> [added line, ...]} for every file the patch touches."""
    out = {}
    current = None
    with io.open(patch_path, encoding='utf-8', errors='replace') as fh:
        for raw in fh:
            line = raw.rstrip('\n').rstrip('\r')
            if line.startswith('+++ '):
                p = line[4:].strip()
                if p == '/dev/null':
                    current = None
                    continue
                # strip the leading b/ that git-style patches carry
                current = p[2:] if p[:2] in ('b/', 'a/') else p
                out.setdefault(current, [])
            elif line.startswith('--- ') or line.startswith('@@'):
                continue
            elif line.startswith('+') and current:
                body = line[1:]
                if len(body.strip()) >= 12 and not BORING.match(body):
                    out[current].append(body)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('tree')
    ap.add_argument('patch')
    ap.add_argument('--sample', type=int, default=4,
                    help='added lines to check per file (default 4)')
    ap.add_argument('--quiet', action='store_true')
    args = ap.parse_args()

    if not os.path.isdir(args.tree):
        print('::error::%s is not a directory' % args.tree, file=sys.stderr)
        return 2
    if not os.path.isfile(args.patch):
        print('::error::%s is not a file' % args.patch, file=sys.stderr)
        return 2

    files = added_lines(args.patch)
    if not files:
        print('::error::%s adds no lines -- nothing to verify' % args.patch, file=sys.stderr)
        return 2

    missing = []
    checked = 0
    absent_files = []
    for rel, lines in sorted(files.items()):
        target = os.path.join(args.tree, rel)
        if not os.path.exists(target):
            # A patch that creates a file is normal; a patch that edits a missing one is not.
            absent_files.append(rel)
            continue
        try:
            body = io.open(target, encoding='utf-8', errors='replace').read()
        except OSError as e:
            print('::error::cannot read %s: %s' % (target, e), file=sys.stderr)
            return 2
        # Spread the sample across the hunks rather than taking the first few, which in a
        # big patch all land in one region.
        step = max(1, len(lines) // args.sample)
        picked = lines[::step][:args.sample]
        for want in picked:
            checked += 1
            if want.strip() not in body:
                missing.append((rel, want.strip()[:100]))

    if missing:
        print('::error::%s is NOT fully applied to %s -- %d of %d sampled added lines are '
              'absent' % (args.patch, args.tree, len(missing), checked))
        for rel, want in missing[:8]:
            print('::error::  %s is missing: %s' % (rel, want))
        print('        The tree carries a different version of this patch. Delete it and '
              're-fetch; do not trust a stamp beside it.', file=sys.stderr)
        return 1

    if not args.quiet:
        print('  ok    %s: %d sampled added lines all present in %s'
              % (os.path.basename(args.patch), checked, args.tree))
        if absent_files:
            print('        (%d file(s) the patch creates were not checked: %s)'
                  % (len(absent_files), ', '.join(absent_files[:3])))
    return 0


if __name__ == '__main__':
    sys.exit(main())
