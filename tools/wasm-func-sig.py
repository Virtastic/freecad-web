# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) Virtastic
"""Report a wasm function's signature, and every direct caller's, by name.

    python tools/wasm-func-sig.py FreeCAD.wasm PyMethod_New [more names...]

WHY: a callee that sees NULL where the caller passed a real pointer means the two
disagree about the signature. Wasm validates direct calls, so a genuine arity
mismatch cannot link -- but a DUPLICATE definition of the same symbol, or an import
resolved to a different function, produces exactly that symptom while validating.
This prints every function whose name matches, its type, and how many distinct
functions share the name, which settles it from the binary rather than from theory.
"""
import io
import sys


def leb_u(b, i):
    r = s = 0
    while True:
        x = b[i]
        i += 1
        r |= (x & 0x7F) << s
        if not x & 0x80:
            return r, i
        s += 7


def parse(path):
    d = io.open(path, 'rb').read()
    assert d[:4] == b'\0asm'
    i = 8
    types = []          # index -> (nparams, nresults)
    imports = []        # imported function type indices, in order
    funcs = []          # defined function type indices, in order
    names = {}          # function index -> name
    while i < len(d):
        sec = d[i]
        i += 1
        size, i = leb_u(d, i)
        end = i + size
        j = i
        if sec == 1:
            cnt, j = leb_u(d, j)
            for _ in range(cnt):
                assert d[j] == 0x60
                j += 1
                np, j = leb_u(d, j)
                j += np
                nr, j = leb_u(d, j)
                j += nr
                types.append((np, nr))
        elif sec == 2:
            cnt, j = leb_u(d, j)
            for _ in range(cnt):
                ml, j = leb_u(d, j)
                j += ml
                nl, j = leb_u(d, j)
                j += nl
                kind = d[j]
                j += 1
                if kind == 0:
                    ti, j = leb_u(d, j)
                    imports.append(ti)
                elif kind == 1:
                    j += 1
                    fl = d[j]
                    j += 1
                    _, j = leb_u(d, j)
                    if fl & 1:
                        _, j = leb_u(d, j)
                elif kind == 2:
                    fl = d[j]
                    j += 1
                    _, j = leb_u(d, j)
                    if fl & 1:
                        _, j = leb_u(d, j)
                    if fl & 4:
                        j += 1
                elif kind == 3:
                    j += 2
        elif sec == 3:
            cnt, j = leb_u(d, j)
            for _ in range(cnt):
                ti, j = leb_u(d, j)
                funcs.append(ti)
        elif sec == 0:
            nl, j = leb_u(d, j)
            nm = d[j:j + nl]
            j += nl
            if nm == b'name':
                while j < end:
                    sub = d[j]
                    j += 1
                    ssz, j = leb_u(d, j)
                    sub_end = j + ssz
                    if sub == 1:      # function names
                        cnt, j = leb_u(d, j)
                        for _ in range(cnt):
                            fi, j = leb_u(d, j)
                            l, j = leb_u(d, j)
                            names[fi] = d[j:j + l].decode('utf-8', 'replace')
                            j += l
                    j = sub_end
        i = end
    return types, imports, funcs, names


def main():
    path = sys.argv[1]
    wanted = sys.argv[2:]
    types, imports, funcs, names = parse(path)
    n_imp = len(imports)
    print('imports=%d defined=%d types=%d named=%d' % (n_imp, len(funcs), len(types), len(names)))

    def sig(fi):
        ti = imports[fi] if fi < n_imp else funcs[fi - n_imp]
        np, nr = types[ti]
        return 'type=%d params=%d results=%d %s' % (ti, np, nr,
                                                    'IMPORTED' if fi < n_imp else 'defined')

    for w in wanted:
        hits = [(fi, nm) for fi, nm in names.items() if nm == w or nm.startswith(w + '.')]
        if not hits:
            print('%-24s NOT FOUND in the name section' % w)
            continue
        for fi, nm in sorted(hits):
            print('%-24s idx=%-7d %s   (name %r)' % (w, fi, sig(fi), nm))
        if len(hits) > 1:
            print('   !! %d functions share this name -- duplicate symbol' % len(hits))


if __name__ == '__main__':
    main()
