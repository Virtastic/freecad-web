# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) Virtastic
"""Stop shiboken's buffer shims hijacking CPython's symbols (RELEASE-PLAN R3).

    python tools/add-buffer-symbol-rename.py

One-shot surgery on patches/pyside-setup.patch. Idempotent: refuses to run twice.

WHY: this is the same defect class that cost the 1.1.3 port its boot. shiboken builds
with Py_LIMITED_API and reimplements a handful of CPython functions; in a shared
libshiboken those stay private, but this port is one static wasm monolith, so they win
the symbols for the whole program -- CPython's own internals included. That is how
shiboken's PyMethod_New, which dereferences a pointer it only fills in later by running
Python code, turned every bound-method creation during interpreter startup into
PyObject_CallFunction(nullptr, ...).

bufferprocs_py37.cpp is the half that was left. The wasm name section shows
PyObject_GetBuffer at index 742 and PyBuffer_Release at 743 -- inside shiboken's object
cluster, not beside CPython's buffer code around 89700 -- so both are still hijacked.
The other five it defines already resolve to CPython, which is precisely the problem
with leaving it to link order: which definition wins is not something to leave to luck.

SAFE BECAUSE the layouts are identical. shiboken's Pep_buffer is a field-for-field
re-declaration of CPython's Py_buffer (buf, obj, len, itemsize, readonly, ndim, format,
shape, strides, suboffsets, internal), and the header does `#define Py_buffer Pep_buffer`,
so a caller typed against Pep_buffer* can bind to CPython's real implementation without
reinterpreting a single byte. Verified against CPython 3.13.3 Include/pybuffer.h.

The renames go in the .cpp only, exactly as the pep384impl group does: shiboken's own
definitions become fcweb_shib_*, every external reference resolves to libpython's real
function, and callers in other translation units get the real implementation too.
"""
import io
import re

PATCH = 'patches/pyside-setup.patch'

RENAMED = [
    'PyObject_GetBuffer',
    'PyBuffer_Release',
    'PyBuffer_IsContiguous',
    'PyBuffer_GetPointer',
    'PyBuffer_FromContiguous',
    'PyBuffer_FillContiguousStrides',
    'PyBuffer_FillInfo',
]

COMMENT = [
    '// FCWEB: same hazard as pep384impl.cpp above. These limited-API stand-ins are not',
    '// private to libshiboken in a static wasm monolith -- they win the symbol for the',
    '// whole program, CPython included. PyObject_GetBuffer and PyBuffer_Release were',
    '// still doing exactly that (wasm indices 742/743, in shiboken\'s object cluster',
    '// rather than beside CPython\'s buffer code), while the other five here happened to',
    '// lose to libpython. Which definition wins is not a thing to leave to link order.',
    '//',
    '// Renaming is safe because Pep_buffer is a field-for-field re-declaration of',
    '// CPython\'s Py_buffer and the header defines one as the other, so shiboken\'s own',
    '// call sites bind to the real implementation without reinterpreting a byte.',
    '#if defined(FCWEB_REAL_CPYTHON) || defined(__EMSCRIPTEN__)',
]


def main():
    raw = io.open(PATCH, 'rb').read()
    crlf = b'\r\n' in raw
    nl = b'\r\n' if crlf else b'\n'
    lines = raw.split(nl)

    if any(b'fcweb_shib_PyObject_GetBuffer' in l for l in lines):
        raise SystemExit('already applied')

    # The existing bufferprocs hunk adds two blank lines right after the include --
    # the slot a previous attempt left behind. Put the renames there.
    anchor = b'+#include "sbkpython.h"' if any(l == b'+#include "sbkpython.h"' for l in lines) else None
    idx = None
    for i, l in enumerate(lines):
        if l == b' #include "sbkpython.h"' and lines[i + 1] == b'+' and lines[i + 2] == b'+':
            idx = i + 1
            break
    if idx is None:
        raise SystemExit('could not find the two added blank lines after sbkpython.h; '
                         'the bufferprocs hunk has changed shape -- re-read it before editing')

    body = ['+' + c for c in COMMENT]
    width = max(len(n) for n in RENAMED)
    body += ['+#  define %-*s fcweb_shib_%s' % (width, n, n) for n in RENAMED]
    body += ['+#endif', '+']
    new = [b.encode() for b in body]

    lines[idx:idx + 2] = new

    # fix the enclosing hunk header's new-side count
    h = max(k for k in range(idx) if lines[k].startswith(b'@@'))
    m = re.match(rb'@@ -(\d+),(\d+) \+(\d+),(\d+) @@', lines[h])
    lines[h] = b'@@ -%s,%s +%s,%d @@' % (m.group(1), m.group(2), m.group(3),
                                         int(m.group(4)) + len(new) - 2)
    io.open(PATCH, 'wb').write(nl.join(lines))
    print('renamed %d buffer symbols; hunk header now %s'
          % (len(RENAMED), lines[h].decode()))


if __name__ == '__main__':
    main()
