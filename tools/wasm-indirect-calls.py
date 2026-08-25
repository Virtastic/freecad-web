# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) Virtastic
"""Show the indirect calls a wasm function makes, and whether the table can satisfy them.

    python tools/wasm-indirect-calls.py FreeCAD.wasm "QEventLoop::exit(int)"
    python tools/wasm-indirect-calls.py FreeCAD.wasm --index 228885

"null function" is what a browser says when a call_indirect lands on a table slot that
holds nothing. The message names the CALLER, which is the one function you already know;
what you need is which slot it reached for and why that slot is empty.

This disassembles the named function far enough to find its call_indirect instructions,
reports the type each one demands, and -- where the index is a constant rather than a
computed vtable load -- says what the element segments actually put there.

A virtual call loads its index from memory, so most call sites here will be reported as
computed. That is still useful: it tells you the trap is a vtable slot rather than a
mis-typed direct call, which is a different bug with a different fix.
"""
import argparse
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


def leb_s(b, i):
    r = s = 0
    while True:
        x = b[i]
        i += 1
        r |= (x & 0x7F) << s
        s += 7
        if not x & 0x80:
            if x & 0x40:
                r |= -(1 << s)
            return r, i


def parse(path):
    d = io.open(path, 'rb').read()
    assert d[:4] == b'\0asm', 'not a wasm binary'
    i = 8
    out = {'names': {}, 'code': [], 'elems': {}, 'types': [], 'nimports': 0}
    while i < len(d):
        sid = d[i]
        i += 1
        size, i = leb_u(d, i)
        end = i + size
        j = i
        if sid == 1:
            cnt, j = leb_u(d, j)
            for _ in range(cnt):
                assert d[j] == 0x60
                j += 1
                np, j = leb_u(d, j)
                j += np
                nr, j = leb_u(d, j)
                j += nr
                out['types'].append(np)
        elif sid == 2:
            cnt, j = leb_u(d, j)
            for _ in range(cnt):
                ml, j = leb_u(d, j)
                j += ml
                nl, j = leb_u(d, j)
                j += nl
                kind = d[j]
                j += 1
                if kind == 0:
                    _, j = leb_u(d, j)
                    out['nimports'] += 1
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
        elif sid == 9:
            cnt, j = leb_u(d, j)
            for _ in range(cnt):
                flags, j = leb_u(d, j)
                if flags != 0:
                    break
                assert d[j] == 0x41
                j += 1
                off, j = leb_s(d, j)
                j += 1               # end opcode
                n, j = leb_u(d, j)
                for k in range(n):
                    fi, j = leb_u(d, j)
                    out['elems'][off + k] = fi
        elif sid == 10:
            cnt, j = leb_u(d, j)
            for _ in range(cnt):
                bsz, j = leb_u(d, j)
                out['code'].append((j, j + bsz))
                j += bsz
        elif sid == 0:
            nl, k = leb_u(d, j)
            nm = d[k:k + nl]
            k += nl
            if nm == b'name':
                while k < end:
                    sub = d[k]
                    k += 1
                    ssz, k = leb_u(d, k)
                    stop = k + ssz
                    if sub == 1:
                        cnt, k = leb_u(d, k)
                        for _ in range(cnt):
                            idx, k = leb_u(d, k)
                            l2, k = leb_u(d, k)
                            out['names'][idx] = d[k:k + l2].decode('utf-8', 'replace')
                            k += l2
                    k = stop
        i = end
    out['raw'] = d
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('wasm')
    ap.add_argument('name', nargs='?')
    ap.add_argument('--index', type=int)
    args = ap.parse_args()

    w = parse(args.wasm)
    idx = args.index
    if idx is None:
        if not args.name:
            sys.exit('give a function name or --index')
        hits = [i for i, n in w['names'].items() if args.name in n]
        if not hits:
            sys.exit('no function matching %r' % args.name)
        idx = hits[0]
    print('function %d: %s' % (idx, w['names'].get(idx, '(unnamed)')))

    body = idx - w['nimports']
    if not (0 <= body < len(w['code'])):
        sys.exit('index %d is an import or out of range' % idx)
    start, end = w['code'][body]
    d = w['raw']

    # Walk the body looking for call_indirect (0x11), remembering the last i32.const.
    i = start
    last_const = None
    found = 0
    # skip locals
    nloc, i = leb_u(d, i)
    for _ in range(nloc):
        _, i = leb_u(d, i)
        i += 1
    while i < end:
        op = d[i]
        i += 1
        if op == 0x41:                      # i32.const
            last_const, i = leb_s(d, i)
        elif op == 0x11:                    # call_indirect
            tidx, i = leb_u(d, i)
            _, i = leb_u(d, i)              # table index
            found += 1
            want = w['types'][tidx] if tidx < len(w['types']) else '?'
            if last_const is not None and last_const in w['elems']:
                tgt = w['elems'][last_const]
                print('  call_indirect type=%d (%s params) via constant slot %d -> function '
                      '%d %s' % (tidx, want, last_const, tgt,
                                 w['names'].get(tgt, '(unnamed)')))
            elif last_const is not None:
                print('  call_indirect type=%d (%s params) via constant slot %d -> SLOT IS '
                      'EMPTY (nothing in any element segment)' % (tidx, want, last_const))
            else:
                print('  call_indirect type=%d (%s params) via a computed index -- a vtable '
                      'load, so the empty slot is in an object, not in this code'
                      % (tidx, want))
            last_const = None
        elif op in (0x10,):                 # call
            _, i = leb_u(d, i)
            last_const = None
        elif op in (0x02, 0x03, 0x04):      # block/loop/if: blocktype
            if d[i] == 0x40:
                i += 1
            else:
                _, i = leb_s(d, i)
        elif op in (0x0C, 0x0D, 0x20, 0x21, 0x22, 0x23, 0x24, 0x25, 0x26):
            _, i = leb_u(d, i)
        elif op == 0x0E:                    # br_table
            n, i = leb_u(d, i)
            for _ in range(n + 1):
                _, i = leb_u(d, i)
        elif op == 0x42:                    # i64.const
            _, i = leb_s(d, i)
        elif op == 0x43:
            i += 4
        elif op == 0x44:
            i += 8
        elif 0x28 <= op <= 0x3E:            # loads/stores: align + offset
            _, i = leb_u(d, i)
            _, i = leb_u(d, i)
        elif op == 0xFC:
            sub, i = leb_u(d, i)
            if sub in (8, 9, 10, 11, 12, 13, 14, 15, 16, 17):
                _, i = leb_u(d, i)
                if sub in (8, 10, 11, 14):
                    _, i = leb_u(d, i)
    print('  %d indirect call site(s)' % found)


if __name__ == '__main__':
    main()
