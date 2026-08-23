# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) Virtastic
"""Ground-truth table-index -> parameter-count map from a wasm binary.

    python tools/wasm-table-arity.py FreeCAD.wasm out.json [sample]

Parses the type, import, function and element sections and emits {table_index: nparams}
for every entry the active element segments place in the indirect function table. This is
exactly what the port's pre-js PyEM_CountArgs must reproduce; comparing the two finds any
arity corruption, which under PY_CALL_TRAMPOLINE turns every C method call into a
wrong-signature cast.
"""
import io
import json
import sys


def leb_u(buf, i):
    r = 0
    s = 0
    while True:
        b = buf[i]
        i += 1
        r |= (b & 0x7F) << s
        if not b & 0x80:
            return r, i
        s += 7


def leb_s(buf, i):
    r = 0
    s = 0
    while True:
        b = buf[i]
        i += 1
        r |= (b & 0x7F) << s
        s += 7
        if not b & 0x80:
            if b & 0x40:
                r |= -(1 << s)
            return r, i


def main():
    path, out = sys.argv[1], sys.argv[2]
    data = io.open(path, 'rb').read()
    assert data[:4] == b'\0asm'
    i = 8
    type_params = []           # type index -> param count
    func_types = []            # defined function index-order -> type index
    import_func_types = []     # imported functions in order -> type index
    elems = {}                 # table index -> function index
    while i < len(data):
        sec = data[i]
        i += 1
        size, i = leb_u(data, i)
        end = i + size
        j = i
        if sec == 1:           # types
            cnt, j = leb_u(data, j)
            for _ in range(cnt):
                form = data[j]
                j += 1
                # rec-group/gc forms would need more handling; MVP funcs are 0x60
                assert form == 0x60, hex(form)
                np, j = leb_u(data, j)
                for _ in range(np):
                    j += 1
                nr, j = leb_u(data, j)
                for _ in range(nr):
                    j += 1
                type_params.append(np)
        elif sec == 2:         # imports
            cnt, j = leb_u(data, j)
            for _ in range(cnt):
                ml, j = leb_u(data, j)
                j += ml
                nl, j = leb_u(data, j)
                j += nl
                kind = data[j]
                j += 1
                if kind == 0:
                    ti, j = leb_u(data, j)
                    import_func_types.append(ti)
                elif kind == 1:
                    j += 1
                    fl = data[j]
                    j += 1
                    _, j = leb_u(data, j)
                    if fl & 1:
                        _, j = leb_u(data, j)
                elif kind == 2:
                    fl = data[j]
                    j += 1
                    _, j = leb_u(data, j)
                    if fl & 1:
                        _, j = leb_u(data, j)
                    if fl & 4:
                        j += 1
                elif kind == 3:
                    j += 2
        elif sec == 3:         # functions
            cnt, j = leb_u(data, j)
            for _ in range(cnt):
                ti, j = leb_u(data, j)
                func_types.append(ti)
        elif sec == 9:         # element segments
            cnt, j = leb_u(data, j)
            for _ in range(cnt):
                flags, j = leb_u(data, j)
                if flags == 0:
                    # active, table 0, offset expr, vec(funcidx)
                    op = data[j]
                    j += 1
                    assert op == 0x41, hex(op)   # i32.const
                    off, j = leb_s(data, j)
                    assert data[j] == 0x0B       # end
                    j += 1
                    n, j = leb_u(data, j)
                    for k in range(n):
                        fi, j = leb_u(data, j)
                        elems[off + k] = fi
                else:
                    raise SystemExit('element segment flags=%d unhandled' % flags)
        i = end

    n_imp = len(import_func_types)

    def params_of(func_idx):
        if func_idx < n_imp:
            return type_params[import_func_types[func_idx]]
        return type_params[func_types[func_idx - n_imp]]

    table = {str(t): params_of(f) for t, f in elems.items()}
    io.open(out, 'w', encoding='utf-8').write(json.dumps(table))
    print('imports=%d funcs=%d types=%d elems=%d -> %s'
          % (n_imp, len(func_types), len(type_params), len(elems), out))


if __name__ == '__main__':
    main()
