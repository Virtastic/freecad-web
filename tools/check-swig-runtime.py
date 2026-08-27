# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) Virtastic
"""One SWIG runtime per binary. Two is a black viewport.

    python3 tools/check-swig-runtime.py build-freecad-gui-weh/bin/FreeCAD.wasm

WHY

FreeCAD compiles a SWIG runtime into itself so it can turn a Python coin node into a C++
SoNode* -- that is how every Python view provider hands its scene graph to the renderer.
pivy carries its own, generated when pivy was built.

SWIG publishes its type table in the interpreter under a VERSION-STAMPED key:
`swig_runtime_data4` for SWIG 4.2.x, `swig_runtime_data5` for 4.4.x. Two runtimes of
different versions in one binary do not share a table and cannot see each other's types.

That shipped. build-python-deps.yml pinned `swig==4.2.1` for pivy; link-freecad.yml
installed `swig` unpinned and got 4.4.1. The linked wasm carried both keys:

    2  swig_runtime_data4      (pivy)
    5  swig_runtime_data5      (FreeCAD)

FreeCAD asked for the table pivy had never registered, so every pointer conversion failed
with `RuntimeError: No SWIG wrapped library loaded`, and:

    File "/freecad/Mod/Assembly/JointObject.py", line 1070, in attach
        vobj.addDisplayMode(self.display_mode, "Wireframe")

Opening a document with Assembly or Draft view providers gave a BLACK VIEWPORT. The app
booted, the payload was complete, the geometry loaded, every gate passed, and nothing drew
-- because the gates build geometry through C++ view providers, which never cross the SWIG
bridge.

WHAT THIS CANNOT SEE

It reads strings out of a binary. It proves the two halves agree on a version; it does not
prove the bridge works. The thing that proves that is opening a document with a PYTHON view
provider and checking something rendered -- worth a gate scenario of its own, because this
failure is invisible to every existing one.
"""
import re
import subprocess
import sys

KEY = re.compile(rb'swig_runtime_data([0-9]+)')


def keys(path):
    """Version-stamped SWIG runtime keys present in the file, with counts."""
    found = {}
    try:
        with open(path, 'rb') as fh:
            blob = fh.read()
    except OSError as e:
        print('::error::cannot read %s (%s)' % (path, e), file=sys.stderr)
        return None
    for m in KEY.finditer(blob):
        v = m.group(1).decode()
        found[v] = found.get(v, 0) + 1
    return found


def main():
    if len(sys.argv) < 2:
        print('usage: check-swig-runtime.py <binary>', file=sys.stderr)
        return 2
    path = sys.argv[1]
    found = keys(path)
    if found is None:
        return 2

    for v in sorted(found):
        print('  swig_runtime_data%s  x%d' % (v, found[v]))

    if not found:
        # FreeCAD always compiles one in. None at all means this is not the binary anyone
        # thinks it is -- which is worth failing over rather than passing quietly.
        print('::error::no SWIG runtime key found in %s at all. FreeCAD always links one, '
              'so either this is the wrong file or the bridge was compiled out.' % path,
              file=sys.stderr)
        return 1

    if len(found) > 1:
        print('::error::%d different SWIG runtime versions in one binary (%s). They stamp '
              'their type tables with different keys and cannot see each other, so every '
              'Python view provider that passes a coin node to C++ will throw "No SWIG '
              'wrapped library loaded" and the viewport will be black. Pin swig to the '
              'SAME version in link-freecad.yml and build-python-deps.yml.'
              % (len(found), ', '.join('swig_runtime_data' + v for v in sorted(found))),
              file=sys.stderr)
        return 1

    print('one SWIG runtime (swig_runtime_data%s) -- FreeCAD and pivy agree'
          % list(found)[0])
    return 0


if __name__ == '__main__':
    sys.exit(main())
