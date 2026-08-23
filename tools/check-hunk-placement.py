# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) Virtastic
"""Check that every ported block still sits in the function it was written for.

    python tools/check-hunk-placement.py OLD.patch NEW.patch

Both must be unified diffs generated with function context in the hunk header -- `diff -p`
or `git diff`, which write:

    @@ -217,6 +226,22 @@ QString FileDialog::getSaveFileName (QWidget * parent, ...

This exists because rebasing a large port is not mainly a text problem. `patch` will happily
place a hunk in a *different function* that happens to look similar, report success, and
produce a file that is brace-balanced, preprocessor-balanced and completely wrong. Three of
those survived every structural check in this repository and were caught only by compiling
FreeCAD:

  * FileDialog.cpp -- the save-path block landed in getSuffixesDescription()'s while loop
    instead of getSaveFileName(), where it referenced `dirName` and returned a QString from
    a void function.
  * PrefWidgets.cpp -- the wasm menu branch landed inside getHistoryGroupName(), between
    its return and its closing brace, so the #else swallowed the end of the enclosing class.
  * View3DInventorViewer.cpp -- the composite blit landed at the end of getDimensions()
    instead of renderScene(), referencing another function's locals.

The invariant here is cheap and exact: an added line that appeared under one function in
the old patch should appear under the same function in the new one. Renames are reported
rather than assumed wrong -- upstream does move code -- but they are reported.

Exits non-zero if any added line changed enclosing function.
"""
import io
import re
import sys
from collections import defaultdict

HUNK = re.compile(r'^@@ -\d+(?:,\d+)? \+\d+(?:,\d+)? @@ ?(.*)$')

# GNU diff truncates the context to about 40 characters where git diff does not, and 1.1.3
# reformatted most signatures anyway -- so comparing the raw string reports every hunk as
# moved. Compare the function NAME, which survives both.
IDENT_BEFORE_PAREN = re.compile(r'([A-Za-z_][A-Za-z0-9_]*)\s*\($')


def context_key(ctx):
    ctx = ctx.strip()
    if not ctx:
        return ''
    head = ctx.split('(')[0]
    m = IDENT_BEFORE_PAREN.search(head + '(')
    if m:
        return m.group(1)
    # No call-like shape: a CMake macro line, a class body, a bare endif(). Truncate to the
    # shorter of the two so a cut-off context still matches its full form.
    return ctx[:28]


def same_context(a, b):
    """Equal, allowing for diff having cut one of them short."""
    ka, kb = context_key(a), context_key(b)
    if ka == kb:
        return True
    # GNU diff cuts the context mid-identifier ("contextMenuEven"), so a long common prefix
    # is the same function, not a different one.
    lo, hi = sorted((ka, kb), key=len)
    return len(lo) >= 6 and hi.startswith(lo)


# "Which function is this in" only means something where there are functions. CMake hunk
# context is whatever line diff last saw -- endif(), a macro header, a configure_file call --
# and comparing those produces noise, not findings.
SKIP_SUFFIXES = ('.cmake', 'CMakeLists.txt')


def added_lines_by_context(path):
    """-> {file: {added line text: context}}, keeping the first context seen for a line."""
    out = defaultdict(dict)
    cur_file, cur_ctx = None, ''
    seen_any_ctx = False
    for raw in io.open(path, encoding='utf-8', errors='replace'):
        line = raw.rstrip('\n').rstrip('\r')
        if line.startswith('--- '):
            name = line[4:].split('\t')[0]
            cur_file = name.split('/', 1)[1] if '/' in name else name
            cur_ctx = ''
            continue
        if line.startswith('+++ ') or line.startswith('diff '):
            continue
        m = HUNK.match(line)
        if m:
            cur_ctx = m.group(1).strip()
            if cur_ctx:
                seen_any_ctx = True
            continue
        if line.startswith('+') and cur_file:
            body = line[1:].strip()
            # Blank lines, braces and lone preprocessor markers say nothing about location.
            if len(body) < 12 or body in ('#endif', '#else', '{', '}'):
                continue
            out[cur_file].setdefault(body, cur_ctx)
    return out, seen_any_ctx


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    old_path, new_path = sys.argv[1], sys.argv[2]
    old, old_ctx = added_lines_by_context(old_path)
    new, new_ctx = added_lines_by_context(new_path)

    for path, has in ((old_path, old_ctx), (new_path, new_ctx)):
        if not has:
            sys.exit('%s has no function context in its hunk headers.\n'
                     'Regenerate it with `diff -p` (or git diff), otherwise this check is '
                     'meaningless.' % path)

    moved, checked, common_files = [], 0, 0
    for f, lines in new.items():
        if f not in old or f.endswith(SKIP_SUFFIXES):
            continue
        common_files += 1
        for body, ctx in lines.items():
            if body not in old[f]:
                continue          # genuinely new in this revision
            was = old[f][body]
            if not was or not ctx:
                continue
            checked += 1
            if not same_context(was, ctx):
                moved.append((f, body, was, ctx))

    print('%d files in both patches, %d added lines compared by enclosing function'
          % (common_files, checked))
    if not moved:
        print('every ported line is still in the function it was written for')
        return

    # group, so one displaced block is one finding rather than twenty
    by_move = defaultdict(list)
    for f, body, was, ctx in moved:
        by_move[(f, was, ctx)].append(body)
    print('\n%d BLOCK(S) CHANGED ENCLOSING FUNCTION:' % len(by_move))
    for (f, was, ctx), bodies in by_move.items():
        print('\n  %s  (%d line%s)' % (f, len(bodies), '' if len(bodies) == 1 else 's'))
        print('    was in: %s' % (was or '(top level)'))
        print('    now in: %s' % (ctx or '(top level)'))
        print('    e.g.    %s' % bodies[0][:88])
    print('\nIf upstream moved this code, update the expectation. If patch(1) moved it, '
          'that is the bug.')
    sys.exit(1)


if __name__ == '__main__':
    main()
