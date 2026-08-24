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

The invariant is WHICH CLUSTER the symbol lands in. Static archives link in order, so
shiboken's objects sit far ahead of CPython's: while a shim owned PyMethod_New it was
function 1112, next to shiboken's Pep* helpers; once the rename takes effect it is 90072,
beside cm_descr_get and func_descr_get in CPython's own classobject.c.

Checking for the renamed fcweb_shib_ names instead would be wrong, and was: with nothing
referencing them any more, the linker garbage-collects the renamed copies, so their ABSENCE
is what success looks like. Their presence is accepted as corroboration, never required.
"""
import importlib.util
import os
import sys

RENAMED = [
    # pep384impl.cpp -- PyMethod_New is the one that cost the port its boot
    'PyMethod_New',
    'PyRun_String',
    'PyMethod_Function',
    'PyMethod_Self',
    'PyStaticMethod_New',
    # bufferprocs_py37.cpp -- the same hazard, found while closing out the first
    'PyObject_GetBuffer',
    'PyBuffer_Release',
    'PyBuffer_IsContiguous',
    'PyBuffer_FromContiguous',
    'PyBuffer_FillInfo',
]

# Two anchors that bracket the link order: a CPython function this port always keeps, and
# a shiboken helper. Each checked symbol must sit nearer the CPython one.
CPYTHON_ANCHOR = 'cm_descr_get'
SHIBOKEN_ANCHOR = '_PepType_Lookup'


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

    def anchor_of(nm):
        hits = by_name.get(nm)
        return min(hits) if hits else None

    cpy = anchor_of(CPYTHON_ANCHOR)
    shib = anchor_of(SHIBOKEN_ANCHOR)
    if cpy is None or shib is None:
        print('::warning::cannot locate both cluster anchors (%s=%s, %s=%s); skipping'
              % (CPYTHON_ANCHOR, cpy, SHIBOKEN_ANCHOR, shib))
        return 0
    print('clusters: CPython near %d, shiboken near %d' % (cpy, shib))

    failures = []
    for nm in RENAMED:
        hits = by_name.get(nm)
        if not hits:
            # Not linked in at all. Nothing can call a shim that is not there.
            print('  ok  %-20s not present in the binary' % nm)
            continue
        idx = min(hits)
        renamed_too = 'fcweb_shib_' + nm in by_name
        if abs(idx - cpy) < abs(idx - shib):
            print("  ok  %-20s at %d, in CPython's cluster%s"
                  % (nm, idx, ' (shim kept too)' if renamed_too else ''))
            continue
        failures.append("%s resolves at index %d -- nearer shiboken's cluster (%d) than "
                        "CPython's (%d), so a limited-API shim owns this symbol. The rename "
                        'in patches/pyside-setup.patch is not taking effect.' % (nm, idx, shib, cpy))

    if failures:
        for f in failures:
            print('::error::%s' % f)
        return 1
    print('no CPython symbols are hijacked by shiboken shims')
    return 0


if __name__ == '__main__':
    sys.exit(main())
