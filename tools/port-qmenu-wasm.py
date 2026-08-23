#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) Virtastic
"""Heap-allocate stack QMenus and make exec() non-blocking, for Qt-for-WebAssembly.

WHY

QMenu::exec() spins a nested event loop. Qt-for-WebAssembly is single-threaded and there is
no ASYNCIFY in this build, so exec() DEADLOCKS: the menu appears and the application stops
responding forever. The port's answer is uniform wherever FreeCAD shows a context menu:

    QMenu menu(this);          ->  QMenu* menu = new QMenu(this);
    menu.addAction(...)        ->  menu->addAction(...)
    someCall(&menu, ...)       ->  someCall(menu, ...)
    menu.exec(pos)             ->  popup(pos) under __EMSCRIPTEN__, exec() elsewhere

The menu must be heap-allocated because popup() returns immediately and the menu has to
outlive the function; WA_DeleteOnClose frees it when it closes.

This was ~20 of the hunks in patches/freecad.patch, repeated almost verbatim per file. Doing
it by hand once per FreeCAD release is how a patch rots, so it is a transformation instead.

USAGE

    python3 tools/port-qmenu-wasm.py <file.cpp> [more.cpp ...]     # rewrites in place
    python3 tools/port-qmenu-wasm.py --dry-run <file.cpp>          # report only

It only touches a function that BOTH declares a stack QMenu and calls exec() on it, so a
menu that is already heap-allocated, or one that is only popup()ed, is left alone. Run it,
then read the diff -- it is a mechanical edit, not a substitute for review.
"""
import re
import sys

FN_START = re.compile(r'^[A-Za-z_][\w:<>,\s\*&]*::\w+\s*\([^;]*\)\s*(const\s*)?\{\s*$', re.M)
DECL = re.compile(r'^(\s*)QMenu\s+(\w+)\s*(\(([^)]*)\))?\s*;\s*$', re.M)


def find_functions(text):
    """Yield (start, end) for each top-level function body: '{' at EOL to '}' at column 0."""
    out = []
    for m in FN_START.finditer(text):
        start = m.start()
        end = text.find('\n}\n', m.end())
        if end == -1:
            continue
        out.append((start, end + 3))
    return out


def port_function(fn):
    m = DECL.search(fn)
    if not m:
        return fn, None
    indent, name, _, ctor = m.group(1), m.group(2), m.group(3), m.group(4)
    if not re.search(r'\b%s\.exec\s*\(' % re.escape(name), fn):
        return fn, None                      # no exec(): nothing that can deadlock

    ctor = (ctor or '').strip()
    heap = '%sQMenu* %s = new QMenu(%s);' % (indent, name, ctor)
    comment = (
        '%s// wasm: QMenu::exec() spins a nested event loop, which DEADLOCKS the\n'
        '%s// single-threaded Qt-for-WebAssembly build. The menu is heap-allocated so it\n'
        '%s// can outlive this function, shown with popup() below, and freed on close.\n'
        % (indent, indent, indent))
    fn = fn[:m.start()] + comment + heap + fn[m.end():]

    fn = re.sub(r'&%s\b' % re.escape(name), name, fn)
    fn = re.sub(r'\b%s\.' % re.escape(name), '%s->' % name, fn)

    # MenuManager::setupContextMenu takes a QMenu&. The stack object was passed by name, so
    # once it becomes a pointer it has to be dereferenced. Missing this compiles nowhere, and
    # it is invisible in a diff that otherwise looks correct.
    fn = re.sub(r'(setupContextMenu\s*\(\s*&view\s*,\s*)%s\b' % re.escape(name),
                r'\1*%s' % name, fn)

    # Any other bare use may want the same treatment -- or may legitimately want the pointer
    # (a QMenu* parameter, a QObject parent, connect()). Report rather than guess.
    bare = sorted({m2.group(0) for m2 in
                   re.finditer(r'[(,]\s*%s\s*[,)]' % re.escape(name), fn)})
    if bare:
        print('    NOTE  %s passed bare: %s  -- check if the callee wants QMenu& (needs *)'
              % (name, ' '.join(bare)))

    # exec(...) -> guarded popup(...)
    ex = re.search(r'^(\s*)%s->exec\s*\(([^;]*)\);\s*$' % re.escape(name), fn, re.M)
    if not ex:
        return fn, name + ' (exec call not on its own line -- CHECK BY HAND)'
    ind, args = ex.group(1), ex.group(2)
    repl = (
        '#if defined(__EMSCRIPTEN__)\n'
        '%s%s->setAttribute(Qt::WA_DeleteOnClose);\n'
        '%s%s->popup(%s);\n'
        '#else\n'
        '%s%s->exec(%s);\n'
        '%s%s->deleteLater();\n'
        '#endif' % (ind, name, ind, name, args, ind, name, args, ind, name))
    fn = fn[:ex.start()] + repl + fn[ex.end():]
    return fn, name


def main():
    argv = sys.argv[1:]
    dry = '--dry-run' in argv
    files = [a for a in argv if not a.startswith('--')]
    if not files:
        print(__doc__)
        return 2
    total = 0
    for path in files:
        raw = open(path, encoding='utf-8', errors='replace').read()
        nl = '\r\n' if '\r\n' in raw else '\n'
        text = raw.replace('\r\n', '\n')
        out, changed = text, []
        # walk backwards so earlier offsets stay valid
        for start, end in reversed(find_functions(text)):
            newfn, name = port_function(out[start:end])
            if name:
                out = out[:start] + newfn + out[end:]
                changed.append(name)
        if changed:
            total += len(changed)
            print('%-58s %s' % (path, ', '.join(reversed(changed))))
            if not dry:
                open(path, 'w', encoding='utf-8', newline=nl).write(out)
    print('\n%d menu(s) ported%s' % (total, ' (dry run)' if dry else ''))
    return 0


if __name__ == '__main__':
    sys.exit(main())
