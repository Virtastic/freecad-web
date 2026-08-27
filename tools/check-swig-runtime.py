# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) Virtastic
"""FreeCAD and pivy must share a SWIG runtime version, or the viewport goes black.

    python3 tools/check-swig-runtime.py build-freecad-gui-weh

WHY

FreeCAD compiles a SWIG runtime into itself so it can turn a Python coin node into a C++
SoNode* -- that is how every Python view provider hands its scene graph to the renderer.
pivy carries its own, generated when pivy was built.

SWIG publishes its type table under a VERSION-STAMPED key: `swig_runtime_data4` for SWIG
4.2.x, `swig_runtime_data5` for 4.4.x. Two runtimes of different versions do not share a
table and cannot see each other's types.

That shipped. build-python-deps.yml pinned swig==4.2.1 for pivy; link-freecad.yml installed
`swig` unpinned and got 4.4.1. FreeCAD then asked for a table pivy had never registered:

    File "/freecad/Mod/Assembly/JointObject.py", line 1070, in attach
        vobj.addDisplayMode(self.display_mode, "Wireframe")
    RuntimeError: No SWIG wrapped library loaded

Opening a document with Assembly or Draft view providers gave a BLACK VIEWPORT. The app
booted, the payload was complete, the geometry loaded, every gate passed, and nothing drew
-- because the gates build geometry through C++ view providers, which never cross the
bridge.

WHAT THIS CHECKS, AND WHY NOT "ONE RUNTIME PER BINARY"

The first version of this asserted that the linked wasm contained exactly ONE
swig_runtime_dataN key. That is the wrong invariant and it failed a build that was
correctly fixed. Traced per-archive, the linked binary legitimately holds two:

    swig_runtime_data4  <- libFreeCADBase.a           FreeCAD
    swig_runtime_data4  <- lib_coin.a                 pivy          <-- these must match
    swig_runtime_data5  <- lib_ifcopenshell_wrapper.a ifcopenshell  <-- independent

ifcopenshell is a separate SWIG module with its own type table, used from Python; it never
hands a pointer to FreeCAD's coin bridge, so its version is nobody else's business. The
requirement is narrower and exact: **FreeCAD and pivy must agree**.

So this compares those two archives directly rather than counting strings in the link
output. If a third party ever does need to interoperate, add it to PEERS with a note
saying why.
"""
import os
import re
import sys

KEY = re.compile(rb'swig_runtime_data([0-9]+)')

# archive basename -> what it is, for the error message. These must agree with each other.
PEERS = {
    'libFreeCADBase.a': "FreeCAD's SWIG bridge",
    'lib_coin.a': 'pivy (the Coin3D bindings)',
}


def versions(path):
    try:
        with open(path, 'rb') as fh:
            blob = fh.read()
    except OSError:
        return set()
    return {m.group(1).decode() for m in KEY.finditer(blob)}


def find(root, name):
    for dirpath, _dirs, files in os.walk(root):
        if name in files:
            return os.path.join(dirpath, name)
    return None


def main():
    if len(sys.argv) < 2:
        print('usage: check-swig-runtime.py <build-or-deps-root> [more roots...]',
              file=sys.stderr)
        return 2
    roots = [r for r in sys.argv[1:] if os.path.isdir(r)]
    if not roots:
        print('::error::none of %s is a directory' % (sys.argv[1:],), file=sys.stderr)
        return 2

    found = {}
    for name in PEERS:
        for root in roots:
            p = find(root, name)
            if p:
                found[name] = (p, versions(p))
                break

    missing = [n for n in PEERS if n not in found]
    if missing:
        # Not finding them is not a pass. It is the check failing to run.
        print('::error::could not find %s under %s -- this check did not run, which is not '
              'the same as it passing' % (', '.join(missing), ', '.join(roots)),
              file=sys.stderr)
        return 2

    ok = True
    seen = {}
    for name, (path, vers) in sorted(found.items()):
        if not vers:
            print('  %-26s %-34s NO SWIG RUNTIME KEY' % (name, PEERS[name]))
            ok = False
            continue
        print('  %-26s %-34s %s'
              % (name, PEERS[name], ', '.join('swig_runtime_data' + v for v in sorted(vers))))
        seen[name] = vers

    if not ok:
        print('::error::an archive that should carry a SWIG runtime does not', file=sys.stderr)
        return 1

    allv = set()
    for v in seen.values():
        allv |= v
    if len(allv) > 1:
        print('::error::FreeCAD and pivy were built with DIFFERENT SWIG runtime versions '
              '(%s). They stamp their type tables with different keys and cannot see each '
              'other, so every Python view provider that passes a coin node to C++ will '
              'throw "No SWIG wrapped library loaded" and the viewport will be black. Pin '
              'swig to the same version in link-freecad.yml and build-python-deps.yml.'
              % ', '.join('swig_runtime_data' + v for v in sorted(allv)), file=sys.stderr)
        return 1

    print('FreeCAD and pivy agree on swig_runtime_data%s' % list(allv)[0])
    return 0


if __name__ == '__main__':
    sys.exit(main())
