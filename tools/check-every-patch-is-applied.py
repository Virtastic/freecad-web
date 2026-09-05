# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) Virtastic
"""Every patch in patches/ must be applied by something.

    python tools/check-every-patch-is-applied.py

Compares the .patch files on disk against the ones patches/apply.sh applies, plus an
explicit list of patches applied elsewhere. An orphan fails the check.

WHY

patches/vtk-expat-wasm-xmlsize.patch was written, committed, reviewed, and named in the
deps cache key so that changing it would rebuild VTK -- and no line in the repository ever
applied it. Its own comment describes, exactly, the failure it was meant to prevent:

    "wasm-ld resolves that signature mismatch to a trapping stub, so
     XML_GetCurrentByteIndex / ColumnNumber / LineNumber blew up with
     RuntimeError: unreachable on the first .vtu parsed"

which is what opening the shipped FEMExample.FCStd did, months later. Worse, someone then
added flags to configure-vtk-weh.sh pushing the width the other way, so the two "fixes"
contradicted each other and neither worked.

Being named in a cache key looks like being wired in. It is not. This check is the
difference, and it costs a millisecond.
"""
import io
import os
import re
import sys

PATCHES = 'patches'
APPLY = 'patches/apply.sh'

# Patches applied by something other than apply.sh: name -> (file, the text that does it).
# Keep this honest -- an entry here is a claim about another file, and the claim is checked.
ELSEWHERE = {
    # build-ccx.yml loops over patches/ccx-*.patch rather than naming each file, which is
    # the shape that cannot go stale: a new ccx patch is picked up by existing code. The
    # claim checked below is that the glob is still there.
    'ccx-cload-arity.patch': ('.github/workflows/build-ccx.yml', 'patches/ccx-*.patch'),
    'ccx-patch-lda.patch': ('.github/workflows/build-ccx.yml', 'patches/ccx-*.patch'),
    'ccx-wasm-automatic-array.patch': ('.github/workflows/build-ccx.yml', 'patches/ccx-*.patch'),
    # Qt is fetched into qt-src/ by its own workflow, not into deps/src/, so apply.sh never
    # sees it; the Qt sources step applies this one itself, zero-fuzz and fail-closed.
    'qt-wasm-embind-int64.patch': ('.github/workflows/build-qt-wasm.yml', 'patches/qt-wasm-embind-int64.patch'),
    # libffi is a release tarball that configure-ctypes.sh fetches into deps/src/libffi
    # itself, outside apply.sh's build-deps run; the same script applies this one,
    # zero-fuzz and fail-closed, before configure.
    'libffi-wasm64-em-js-deps.patch': ('configure-ctypes.sh', 'patches/libffi-wasm64-em-js-deps.patch'),
}


def main():
    on_disk = {f for f in os.listdir(PATCHES) if f.endswith('.patch')}
    apply_sh = io.open(APPLY, encoding='utf-8').read()
    applied = set(re.findall(r'apply_one\s+\S+\s+(\S+\.patch)', apply_sh))

    rc = 0
    for name in sorted(on_disk - applied - set(ELSEWHERE)):
        print('::error::patches/%s is never applied by anything. Add it to %s, or to '
              'ELSEWHERE in this script with the file that does apply it.' % (name, APPLY))
        rc = 1

    for name, (where, needle) in sorted(ELSEWHERE.items()):
        if name not in on_disk:
            continue
        try:
            text = io.open(where, encoding='utf-8', errors='replace').read()
        except OSError:
            print('::error::%s is claimed to apply patches/%s, and does not exist'
                  % (where, name))
            rc = 1
            continue
        if needle not in text:
            print('::error::%s no longer contains %r, so nothing applies patches/%s'
                  % (where, needle, name))
            rc = 1

    for name in sorted(applied - on_disk):
        print('::error::%s applies patches/%s, which is not on disk' % (APPLY, name))
        rc = 1

    if rc == 0:
        print('  ok    all %d patches are applied by something' % len(on_disk))
    return rc


if __name__ == '__main__':
    sys.exit(main())
