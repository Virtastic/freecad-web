# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) Virtastic
"""Register PySide6.QtNetwork as a builtin and expose it from the package glue.

    python tools/add-qtnetwork-inittab.py

Surgery on port-authored lines in patches/freecad.patch plus the pyside-pkg glue, so the
pristine-diff regenerator cannot express it. Idempotent.

WHY

QtNetwork's bindings are built and its archive is in the link, and it still could not be
imported:

    from PySide6 import QtNetwork
    ImportError: cannot import name 'QtNetwork' from 'PySide6'

Two things were missing, and the archive being present hid both. The binding modules are
compiled into the executable, so they are only reachable if MainGui.cpp registers their
PyInit_* in the inittab -- under an underscore name, because a dotted inittab entry breaks
CPython's importlib bootstrap. And PySide6/__init__.py then has to alias that builtin to
its canonical dotted name, which is what makes `from PySide6 import QtNetwork` and
Shiboken's own cross-module lookups resolve.

Without both, the Addon Manager reports "No viable version of PySide was found", which
names the wrapper rather than the missing module -- and the FreeCAD PySide shim reports
"No module named 'PySide6.QtNetwork'", which at least says what it wanted.
"""
import io
import re

PATCH = 'patches/freecad.patch'
GLUE = 'patches/pyside-pkg-glue/PySide6/__init__.py'


def patch_inittab():
    raw = io.open(PATCH, 'rb').read()
    if b'QtNetwork_fcweb' in raw:
        print('  inittab: already registered')
        return raw, False

    decl = b'+extern "C" PyObject* PyInit_QtWidgets();'
    if raw.count(decl) != 1:
        raise SystemExit('the PyInit_QtWidgets declaration was not found exactly once')
    raw = raw.replace(
        decl,
        decl + b'\n+extern "C" PyObject* PyInit_QtNetwork();  '
               b'// the Addon Manager fetches over QtNetwork',
        1)

    reg = b'+    PyImport_AppendInittab("QtWidgets_fcweb", PyInit_QtWidgets);'
    if raw.count(reg) != 1:
        raise SystemExit('the QtWidgets inittab registration was not found exactly once')
    raw = raw.replace(
        reg,
        reg + b'\n+    PyImport_AppendInittab("QtNetwork_fcweb", PyInit_QtNetwork);',
        1)
    return raw, True


def grow_hunks(raw):
    """Each edit added one line to a hunk; widen the two headers that contain them."""
    for needle in (b'PyInit_QtNetwork();', b'"QtNetwork_fcweb", PyInit_QtNetwork'):
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


def patch_glue():
    src = io.open(GLUE, encoding='utf-8', newline='').read()
    if 'QtNetwork' in src:
        print('  glue: already exposes QtNetwork')
        return False
    nl = '\r\n' if '\r\n' in src else '\n'
    src = src.replace('__all__ = ["QtCore", "QtGui", "QtWidgets"]',
                      '__all__ = ["QtCore", "QtGui", "QtWidgets", "QtNetwork"]', 1)
    src = src.rstrip(nl) + nl + nl.join([
        '',
        '# QtNetwork last: it needs QtCore, and nothing above needs it. The Addon Manager is',
        '# the reason it is here -- NetworkManager.py imports it before doing anything else,',
        '# so without this the workbench installs and then cannot fetch a thing.',
        'QtNetwork = importlib.import_module("QtNetwork_fcweb")',
        'sys.modules["PySide6.QtNetwork"] = QtNetwork',
        '',
    ])
    io.open(GLUE, 'w', encoding='utf-8', newline='').write(src)
    return True


def main():
    raw, changed = patch_inittab()
    if changed:
        raw = grow_hunks(raw)
        io.open(PATCH, 'wb').write(raw)
        print('  inittab: QtNetwork_fcweb registered')
    if patch_glue():
        print('  glue: PySide6.QtNetwork exposed')


if __name__ == '__main__':
    main()
