# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) Virtastic
"""Every registered PySide module must have its archive on the link line.

    python tools/check-pyside-link-line.py

Cross-checks three places that have to agree about which PySide6 modules this build has:

  * patches/freecad.patch  -- PyImport_AppendInittab("Qt<M>_fcweb", PyInit_Qt<M>)
  * configure-gui-weh.sh   -- PySide6/Qt<M>/Qt<M>.cpython-313-wasm64-emscripten.a on the link line
  * rebuild-pyside-weh.sh  -- -DMODULES="...;Qt<M> without the Qt prefix..."

WHY

QtNetwork was built, its archive was checked for PyInit_QtNetwork by the link preflight,
the inittab registration was added, the package glue aliased it -- and the link still
died after two hours of compiling:

    wasm-ld: error: MainGui.cpp.o: undefined symbol: PyInit_QtNetwork

because the archive was never added to the link line. Four of the five things needed were
in place, each one verified, and the missing one was the only one nothing looked at. A
preflight that checks an archive exists is not the same as checking it is linked.
"""
import io
import re
import sys

PATCH = 'patches/freecad.patch'
# BOTH files carry a link line, and they drifted. configure-gui-weh.sh is what a
# person reads; scratchpad/linkcmds/fc-linkcmd-weh.sh is what CI actually runs (see the
# Link step in link-freecad.yml). QtSvg was added to the first and not the second, so the
# check passed and the link died on "undefined symbol: PyInit_QtSvg" an hour later.
CONFIGURE = 'configure-gui-weh.sh'
LINKCMD = 'scratchpad/linkcmds/fc-linkcmd-weh.sh'
REBUILD = 'rebuild-pyside-weh.sh'


def read(path):
    return io.open(path, encoding='utf-8', errors='replace').read()


def main():
    patch = read(PATCH)
    rebuild = read(REBUILD)
    line_files = {CONFIGURE: read(CONFIGURE), LINKCMD: read(LINKCMD)}

    registered = set(re.findall(r'PyImport_AppendInittab\("(Qt\w+)_fcweb"', patch))
    if not registered:
        print('::error::no PySide inittab registrations found in %s -- has the patch '
              'stopped registering the bindings?' % PATCH)
        return 1

    linked_in = {f: set(re.findall(r'PySide6/(Qt\w+)/Qt\w+\.cpython-313-wasm64-emscripten\.a', text))
                 for f, text in line_files.items()}
    linked = set.intersection(*linked_in.values()) if linked_in else set()
    built = set()
    # rebuild-pyside-weh.sh single-sources the list into PYSIDE_MODULES and passes that
    # to -DMODULES, so read the variable and fall back to a literal list.
    m = (re.search(r'PYSIDE_MODULES="([^"$]+)"', rebuild)
         or re.search(r'-DMODULES="([^"$]+)"', rebuild))
    if m:
        built = {'Qt' + x.strip() for x in m.group(1).split(';') if x.strip()}

    rc = 0
    for mod in sorted(registered):
        for f, mods in sorted(linked_in.items()):
            if mod not in mods:
                print('::error::%s is registered in the inittab but its archive is not on '
                      'the link line in %s -- the link will fail with "undefined symbol: '
                      'PyInit_%s"' % (mod, f, mod))
                rc = 1
        if built and mod not in built:
            print('::error::%s is registered in the inittab but %s does not build it'
                  % (mod, REBUILD))
            rc = 1
    for mod in sorted(set.union(*linked_in.values()) - registered) if linked_in else []:
        print('::error::%s is linked in but never registered in the inittab, so nothing '
              'can import it -- this is how "No viable version of PySide was found" '
              'happens' % mod)
        rc = 1

    if rc == 0:
        print('  ok    PySide modules agree: %s' % ', '.join(sorted(registered)))
    return rc


if __name__ == '__main__':
    sys.exit(main())
