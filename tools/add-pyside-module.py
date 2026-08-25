# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) Virtastic
"""Wire one more PySide6 module into the static build.

    python tools/add-pyside-module.py QtSvg "why it is needed"

Does the two edits that cannot be regenerated from a pristine diff:

  * patches/freecad.patch  -- the PyInit_<M> declaration and its PyImport_AppendInittab
    entry in MainGui.cpp, under an underscore name, because a dotted inittab entry breaks
    CPython's importlib bootstrap;
  * patches/pyside-pkg-glue/PySide6/__init__.py -- the alias from that builtin to the
    canonical dotted name, which is what makes `from PySide6 import <M>` and Shiboken's
    own cross-module lookups resolve.

The other three places are ordinary edits and are checked by
tools/check-pyside-link-line.py: the module list in rebuild-pyside-weh.sh, the archive on
the link line in configure-gui-weh.sh, and the preflight in link-freecad.yml.

Idempotent.

WHY

This was a one-off script for QtNetwork. It is general now because it happened twice: the
Addon Manager's PySideWrapper.py imports

    from PySide import QtCore, QtGui, QtNetwork, QtSvg, QtWidgets

as a single statement, so a build missing ANY of those five reports the same thing --
"No viable version of PySide was found" -- which names the wrapper rather than the module.
QtNetwork was the first missing one. Fixing it revealed QtSvg behind it.
"""
import io
import re
import sys

PATCH = 'patches/freecad.patch'
GLUE = 'patches/pyside-pkg-glue/PySide6/__init__.py'


def patch_inittab(module, why):
    raw = io.open(PATCH, 'rb').read()
    if ('%s_fcweb' % module).encode() in raw:
        print('  inittab: %s already registered' % module)
        return raw, False

    anchor = b'+extern "C" PyObject* PyInit_QtWidgets();'
    if raw.count(anchor) != 1:
        raise SystemExit('the PyInit_QtWidgets declaration was not found exactly once')
    decl = b'\n+extern "C" PyObject* PyInit_%s();' % module.encode()
    if why:
        decl += b'  // %s' % why.encode()
    raw = raw.replace(anchor, anchor + decl, 1)

    reg = b'+    PyImport_AppendInittab("QtWidgets_fcweb", PyInit_QtWidgets);'
    if raw.count(reg) != 1:
        raise SystemExit('the QtWidgets inittab registration was not found exactly once')
    raw = raw.replace(
        reg,
        reg + b'\n+    PyImport_AppendInittab("%s_fcweb", PyInit_%s);'
              % (module.encode(), module.encode()),
        1)
    return raw, True


def grow_hunks(raw, module):
    """Each edit added one line to a hunk; widen the two headers that contain them."""
    for needle in (b'PyInit_%s();' % module.encode(),
                   b'"%s_fcweb", PyInit_%s' % (module.encode(), module.encode())):
        pos = raw.find(needle)
        if pos < 0:
            continue
        start = raw.rfind(b'\n@@ ', 0, pos) + 1
        end = raw.find(b'\n', start)
        m = re.match(rb'@@ -(\d+),(\d+) \+(\d+),(\d+) @@(.*)$', raw[start:end], re.S)
        if not m:
            raise SystemExit('could not parse the hunk header above %r' % needle)
        grown = b'@@ -%s,%s +%s,%d @@%s' % (m.group(1), m.group(2), m.group(3),
                                            int(m.group(4)) + 1, m.group(5))
        raw = raw[:start] + grown + raw[end:]
    return raw


def patch_glue(module, why):
    src = io.open(GLUE, encoding='utf-8', newline='').read()
    if module in src:
        print('  glue: already exposes %s' % module)
        return False
    nl = '\r\n' if '\r\n' in src else '\n'
    m = re.search(r'__all__ = \[([^\]]*)\]', src)
    if not m:
        raise SystemExit('could not find __all__ in the glue')
    src = src.replace(m.group(0),
                      '__all__ = [%s, "%s"]' % (m.group(1), module), 1)
    lines = ['']
    if why:
        lines += ['# ' + why]
    lines += ['%s = importlib.import_module("%s_fcweb")' % (module, module),
              'sys.modules["PySide6.%s"] = %s' % (module, module),
              '']
    src = src.rstrip(nl) + nl + nl.join(lines)
    io.open(GLUE, 'w', encoding='utf-8', newline='').write(src)
    return True


def main():
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    module = sys.argv[1]
    why = sys.argv[2] if len(sys.argv) > 2 else ''
    if not re.match(r'^Qt\w+$', module):
        raise SystemExit('module should look like QtSvg, not %r' % module)

    raw, changed = patch_inittab(module, why)
    if changed:
        raw = grow_hunks(raw, module)
        io.open(PATCH, 'wb').write(raw)
        print('  inittab: %s_fcweb registered' % module)
    if patch_glue(module, why):
        print('  glue: PySide6.%s exposed' % module)
    print('  now add the archive to configure-gui-weh.sh, the module to '
          'rebuild-pyside-weh.sh, and the preflight line to link-freecad.yml -- '
          'tools/check-pyside-link-line.py checks all three.')


if __name__ == '__main__':
    main()
