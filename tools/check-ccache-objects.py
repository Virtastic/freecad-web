# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) Virtastic
"""Does ccache hand back the object the compiler would actually produce?

    python3 tools/check-ccache-objects.py build-freecad-gui-weh [--sample 15]

WHY THIS EXISTS

`ccache -s` proves ccache RAN. It says nothing about whether the object it served is the
object clang would produce for that input right now. That gap is precisely the one this
project keeps falling into -- a claim stored beside a thing, and nothing tying the claim to
the thing's content. `patches/apply.sh` grew `verify-patch-applied.py` for the same reason:
a marker said "patched" and the tree was not.

ccache is structurally better than a stamp -- its key IS a hash of the source, every
included header, the command line and the compiler -- but "structurally better" is an
argument, and this checks instead.

HOW

For a deterministic sample of objects spread across modules: ask ninja for the exact command
it used, re-run that command with CCACHE_DISABLE=1 into a temp file, and compare sha256.
A mismatch means the object in the build tree is not what the compiler produces.

WHAT A FAILURE ACTUALLY MEANS

Not necessarily that ccache is wrong. Wasm objects should be bit-reproducible -- no
timestamps, deterministic symbol order -- but if that turns out not to hold, this reports a
mismatch for a benign reason. That is why it starts advisory: run it once against a
CCACHE_DISABLE=1 build and confirm 15/15 before anyone treats a failure as a defect. If
objects prove not to be bit-identical, compare `llvm-nm --defined-only` and section sizes
instead -- weaker, but it still catches the failures that matter (missing symbols, wrong
exception model, wrong optimisation level).
"""
import argparse
import hashlib
import os
import re
import shlex
import subprocess
import sys
import tempfile

# Spread the sample across modules rather than taking the first N, so a fault confined to
# one workbench's flags cannot hide behind fifteen samples from another.
WANT = ('src/App', 'src/Gui', 'src/Base', 'src/Mod/Part', 'src/Mod/PartDesign',
        'src/Mod/Sketcher', 'src/Mod/Fem', 'src/Mod/Draft', 'src/Mod/CAM',
        'src/Mod/Mesh', 'src/Mod/Import', 'src/Mod/Spreadsheet', 'src/Mod/Measure',
        'src/Mod/Material', 'src/Mod/Points')


def sh(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def targets(build):
    """Object files ninja knows about, one per module prefix, in a stable order."""
    r = sh(['ninja', '-C', build, '-t', 'targets', 'all'])
    if r.returncode != 0:
        return []
    objs = sorted(l.split(':')[0] for l in r.stdout.split(chr(10))
                  if l.endswith('.o') or '.o:' in l)
    objs = [o for o in objs if o.endswith('.o')]
    picked = []
    for pre in WANT:
        for o in objs:
            if o.startswith(pre):
                picked.append(o)
                break
    return picked


def command_for(build, target):
    r = sh(['ninja', '-C', build, '-t', 'commands', target])
    if r.returncode != 0:
        return None
    # The last command is the one that produces the target.
    cmds = [c for c in r.stdout.split(chr(10)) if c.strip()]
    return cmds[-1] if cmds else None


def sha(path):
    h = hashlib.sha256()
    with open(path, 'rb') as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('build', nargs='?', default='build-freecad-gui-weh')
    ap.add_argument('--sample', type=int, default=15)
    args = ap.parse_args()

    if not os.path.isdir(args.build):
        print('::error::%s is not a build directory' % args.build, file=sys.stderr)
        return 2

    picked = targets(args.build)[:args.sample]
    if not picked:
        print('::error::no object targets found in %s -- nothing was checked, which is not '
              'the same as nothing being wrong' % args.build, file=sys.stderr)
        return 2

    env = dict(os.environ)
    env['CCACHE_DISABLE'] = '1'
    env.pop('EM_COMPILER_WRAPPER', None)

    tmp = tempfile.mkdtemp(prefix='fcverify-')
    ok = mismatch = skipped = 0
    for n, t in enumerate(picked):
        built = os.path.join(args.build, t)
        if not os.path.exists(built):
            skipped += 1
            continue
        cmd = command_for(args.build, t)
        if not cmd:
            skipped += 1
            continue
        out = os.path.join(tmp, '%02d.o' % n)
        # Redirect the command's -o to our temp file. The compile line always names it.
        fresh = re.sub(r'-o\s+' + re.escape(t), '-o ' + shlex.quote(out), cmd)
        if fresh == cmd:
            skipped += 1
            continue
        r = subprocess.run(fresh, shell=True, cwd=args.build, env=env,
                           capture_output=True, text=True)
        if r.returncode != 0 or not os.path.exists(out):
            print('  SKIP     %s (recompile failed: %s)'
                  % (t, (r.stderr or '').strip().split(chr(10))[-1][:80]))
            skipped += 1
            continue
        a, b = sha(built), sha(out)
        if a == b:
            ok += 1
            print('  match    %s' % t)
        else:
            mismatch += 1
            print('  MISMATCH %s' % t)
            print('           in tree: %s' % a[:32])
            print('           fresh:   %s' % b[:32])

    print('')
    print('%d matched, %d MISMATCHED, %d skipped (of %d sampled)'
          % (ok, mismatch, skipped, len(picked)))
    if mismatch:
        print('::error::%d object(s) in the build tree differ from what the compiler '
              'produces now. Either the compile cache served a stale object, or these '
              'objects are not bit-reproducible -- check which before trusting either '
              'answer.' % mismatch, file=sys.stderr)
        return 1
    if ok == 0:
        print('::error::nothing was actually compared, so this proves nothing',
              file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
