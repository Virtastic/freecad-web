# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) Virtastic
"""Fail the link if shiboken's limited-API shims have hijacked CPython's symbols.

    python tools/check-symbol-hijack.py <FreeCAD.wasm>

THE REGRESSION THIS CATCHES

shiboken is built with Py_LIMITED_API, where CPython hides a handful of functions,
so pep384impl.cpp defines its own stand-ins: PyMethod_New, PyRun_String,
PyMethod_Function, PyMethod_Self, PyStaticMethod_New. In a SHARED libshiboken those
stay private. This port links one static wasm monolith, so a stand-in wins the
symbol program-wide -- CPython's own internals included.

That is not hypothetical: PyMethod_New's stand-in dereferences PepMethod_TypePtr,
which shiboken fills in later by running Python code, so while it held the symbol
every bound-method creation during interpreter startup raised
"SystemError: null argument to internal routine" and FreeCAD could not boot at all.
patches/pyside-setup.patch renames the definitions out of the way -- but that
rename sat behind a macro defined nowhere and was silently inert for the whole of
the 1.1.3 port. A guard that can go quiet is not a guard, so this checks the linked
binary instead of trusting the build flags.

The invariant: every renamed stand-in is present under its fcweb_shib_ name, and
none of the hijacked names resolves into shiboken's object-file cluster.
"""
import importlib.util
import os
import sys

RENAMED = [
    'PyMethod_New',
    'PyRun_String',
    'PyMethod_Function',
    'PyMethod_Self',
    'PyStaticMethod_New',
]

# A CPython function this port is known to keep, used to locate the CPython cluster.
CPYTHON_ANCHOR = 'cm_descr_get'


def load_parser():
    here = os.path.dirname(os.path.abspath(__file__))
    spec = importlib.util.spec_from_file_location('wfs', os.path.join(here, 'wasm-func-sig.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main():
    if len(sys.argv) < 2:
        print('usage: check-symbol-hijack.py <FreeCAD.wasm>', file=sys.stderr)
        return 2
    m = load_parser()
    _types, imports, funcs, names = m.parse(sys.argv[1])
    if not names:
        print('::warning::no name section in this wasm -- cannot check for symbol hijacking; '
              'the link normally keeps it via --profiling-funcs')
        return 0

    by_name = {}
    for idx, nm in names.items():
        by_name.setdefault(nm, []).append(idx)

    anchor = by_name.get(CPYTHON_ANCHOR)
    if not anchor:
        print('::warning::%s not found; skipping the cluster check' % CPYTHON_ANCHOR)
        anchor_idx = None
    else:
        anchor_idx = min(anchor)

    failures = []
    for nm in RENAMED:
        shimmed = by_name.get('fcweb_shib_' + nm)
        real = by_name.get(nm)
        if not shimmed:
            failures.append('%s: shiboken\'s stand-in is NOT renamed (fcweb_shib_%s absent) -- '
                            'the guard in patches/pyside-setup.patch went inert again' % (nm, nm))
            continue
        if real and anchor_idx is not None:
            # shiboken's objects link far ahead of CPython's; a hijacked symbol shows up
            # in shiboken's index range instead of beside its own translation unit.
            idx = min(real)
            if idx < anchor_idx // 2:
                failures.append('%s resolves at index %d, far from CPython\'s cluster near %d '
                                '-- it looks like a shim still owns this symbol'
                                % (nm, idx, anchor_idx))
        print('  ok  %-20s renamed stand-in present%s'
              % (nm, '' if not real else ', real symbol at %d' % min(real)))

    if failures:
        for f in failures:
            print('::error::%s' % f)
        return 1
    print('no CPython symbols are hijacked by shiboken shims')
    return 0


if __name__ == '__main__':
    sys.exit(main())
