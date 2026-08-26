# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) Virtastic
"""Decide whether a change to the engine costs the user anything, by booting both.

    python tools/boot-compare.py --a serve-2gb --b serve-4gb --runs 5

WHY THIS EXISTS

Memory growth is the immediate question -- `ALLOW_MEMORY_GROWTH=1` adds a bounds check to
every heap access, and emscripten warns in this exact toolchain that `-pthread` together
with growth "may run non-wasm code slowly". But the question recurs every time the link
line changes, and answering it by hand is how it stops being answered.

WHY IT INTERLEAVES

The obvious method -- boot A five times, boot B five times, compare -- measures the machine
as much as the build. On this laptop the same serve tree booted in 14 s and in 23 s twenty
minutes apart, purely because of what else was running. Five A runs followed by five B runs
would attribute all of that drift to the change under test.

So the runs alternate A, B, A, B. Load that drifts over the session hits both sides roughly
equally, and the pairing is what makes the comparison mean anything.

WHAT IT WILL NOT DO

It will not report a difference smaller than the spread of the runs themselves. Boot time
here has a spread of several seconds; a 4% median difference inside a 40% spread is not a
finding, and printing it as one would be worse than printing nothing.

Three frame-time benchmarks were written for this same question and all three were deleted
rather than shipped, because each produced a number that did not move when the thing it
claimed to measure moved. Boot time is used instead because a 2 GB baseline was already
recorded with it: 7, 9, 9, 11, 11 s, median 9.
"""
import argparse
import os
import re
import subprocess
import sys

READY = re.compile(r'==> Ready in ([0-9.]+)s')
HEAP = re.compile(r'==> heap: (\d+) MB, growable=(\w+)')


def boot_once(tree, port, timeout):
    """One boot of one serve tree. Returns (seconds, heap_mb, growable) or None."""
    cmd = [sys.executable, '-u', os.path.join('tools', 'boot-gate.py'), tree,
           '--scenario', 'boot', '--port', str(port), '--timeout', str(timeout)]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 120)
    except subprocess.TimeoutExpired:
        return None
    out = (p.stdout or '') + (p.returncode and (p.stderr or '') or '')
    m, h = READY.search(out), HEAP.search(out)
    if p.returncode != 0 or not m:
        sys.stdout.write('    boot failed (exit %s)%s\n'
                         % (p.returncode,
                            ': ' + (p.stderr or '').strip().splitlines()[-1][:120]
                            if (p.stderr or '').strip() else ''))
        return None
    return (float(m.group(1)),
            int(h.group(1)) if h else None,
            h.group(2) if h else '?')


def stats(v):
    s = sorted(v)
    n = len(s)
    return {
        'n': n,
        'min': s[0],
        'max': s[-1],
        'median': s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--a', required=True, help='reference serve tree')
    ap.add_argument('--b', required=True, help='candidate serve tree')
    ap.add_argument('--runs', type=int, default=5, help='boots of each (default: %(default)s)')
    ap.add_argument('--port', type=int, default=9600, help='first port to use')
    ap.add_argument('--timeout', type=int, default=600)
    args = ap.parse_args()

    for t in (args.a, args.b):
        if not os.path.exists(os.path.join(t, 'FreeCAD.wasm')):
            raise SystemExit('%s does not look like a serve tree (no FreeCAD.wasm)' % t)

    print('A (reference): %s' % args.a)
    print('B (candidate): %s' % args.b)
    print('%d boot(s) of each, alternating, so drift in machine load hits both sides'
          % args.runs)
    print('')

    ta, tb, heaps = [], [], {}
    port = args.port

    # One uncounted boot of each first. The first read of a 100 MB wasm and a 190 MB data
    # package comes off disk; every later one comes out of the OS page cache. Without this
    # the first tree booted carries a penalty that has nothing to do with the build.
    print('  warmup (not counted)')
    for tree in (args.a, args.b):
        boot_once(tree, port, args.timeout)
        port += 1

    for i in range(args.runs):
        # Alternate which side goes first. Even after a warmup the first of a pair tends to
        # run in a quieter machine than the second, and a fixed order turns that into a
        # consistent bias -- measured: comparing one tree against ITSELF reported B 15%
        # faster, purely because A always went first.
        order = (('A', args.a, ta), ('B', args.b, tb))
        if i % 2:
            order = tuple(reversed(order))
        for label, tree, acc in order:
            r = boot_once(tree, port, args.timeout)
            port += 1
            if r is None:
                print('  %d%s: FAILED to boot' % (i + 1, label))
                continue
            secs, heap, grow = r
            acc.append(secs)
            heaps[label] = (heap, grow)
            print('  %d%s  %5.1f s   heap %s MB growable=%s' % (i + 1, label, secs, heap, grow))
    print('')

    if not ta or not tb:
        print('::error::one side never booted, so there is nothing to compare')
        return 1

    sa, sb = stats(ta), stats(tb)
    for label, s, h in (('A', sa, heaps.get('A')), ('B', sb, heaps.get('B'))):
        print('%s  n=%d  median %.1f s   range %.1f-%.1f s   heap %s MB growable=%s'
              % (label, s['n'], s['median'], s['min'], s['max'],
                 h[0] if h else '?', h[1] if h else '?'))
    print('')

    delta = sb['median'] - sa['median']
    pct = 100.0 * delta / sa['median'] if sa['median'] else 0.0
    print('B is %+.1f s (%+.1f%%) against A at the median.' % (delta, pct))

    # The test for "is this real" is whether the two sets of runs OVERLAP at all. With a
    # handful of runs there is no honest way to resolve a difference smaller than the
    # spread, and an ad-hoc noise floor gets this wrong: the first version of this tool
    # scaled the floor to half the combined range, and declared a tree 15% faster than
    # itself. Disjoint ranges is a criterion that cannot do that.
    overlap = sa['min'] <= sb['max'] and sb['min'] <= sa['max']
    if overlap:
        print('The two sets of runs OVERLAP (A %.1f-%.1f, B %.1f-%.1f), so this measurement '
              'does not show a difference. It does not show they are equal either -- it '
              'shows any effect is smaller than %d runs on this machine can resolve. Raise '
              '--runs, or measure somewhere quieter, before concluding anything.'
              % (sa['min'], sa['max'], sb['min'], sb['max'], args.runs))
    else:
        print('The two sets of runs do NOT overlap (A %.1f-%.1f, B %.1f-%.1f). B is '
              'genuinely %s to boot on this machine.'
              % (sa['min'], sa['max'], sb['min'], sb['max'],
                 'slower' if delta > 0 else 'faster'))
    return 0


if __name__ == '__main__':
    sys.exit(main())
