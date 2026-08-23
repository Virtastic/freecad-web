# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) Virtastic
"""Which static initializer calls a given function? Answered from the wasm binary itself.

    python tools/find-ctor-caller.py FreeCAD.wasm "ViewParams::instance"

Needs a name section (--profiling-funcs). Finds the target's function index, then scans
every function whose name marks it as a per-TU static initializer (_GLOBAL__sub_I_*,
__cxx_global_var_init*) for a direct `call` to it. The initializer's NAME carries the
translation unit, which is the answer the stack trace could not give: binaryen had inlined
the initializer frame between __wasm_call_ctors and the callee.

The body scan is a byte scan for opcode 0x10 (call) + LEB128 target, not a full decoder.
0x10 can appear inside operands, so a hit is confirmed by re-encoding the target's LEB and
requiring the exact byte sequence -- false positives are unlikely at 5-byte lengths and
harmless (they would only add a candidate to inspect).
"""
import io
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


def enc_leb(n):
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def main():
    path, needle = sys.argv[1], sys.argv[2]
    data = io.open(path, 'rb').read()
    assert data[:4] == b'\0asm'
    i = 8
    n_imported_funcs = 0
    code_entries = []          # (func_index, body_bytes)
    names = {}                 # func_index -> name
    while i < len(data):
        sec_id = data[i]
        i += 1
        size, i = leb_u(data, i)
        end = i + size
        if sec_id == 2:        # imports: count function imports for index base
            cnt, j = leb_u(data, i)
            for _ in range(cnt):
                mlen, j = leb_u(data, j)
                j += mlen
                nlen, j = leb_u(data, j)
                j += nlen
                kind = data[j]
                j += 1
                if kind == 0:
                    _, j = leb_u(data, j)
                    n_imported_funcs += 1
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
        elif sec_id == 10:     # code
            cnt, j = leb_u(data, j0 := i)
            j = j0
            cnt, j = leb_u(data, j)
            for k in range(cnt):
                bsz, j = leb_u(data, j)
                code_entries.append((n_imported_funcs + k, j, bsz))
                j += bsz
        elif sec_id == 0:      # custom -- find "name"
            nlen, j = leb_u(data, i)
            nm = data[j:j + nlen]
            j += nlen
            if nm == b'name':
                while j < end:
                    sub = data[j]
                    j += 1
                    ssz, j = leb_u(data, j)
                    send = j + ssz
                    if sub == 1:
                        cnt, j2 = leb_u(data, j)
                        for _ in range(cnt):
                            idx, j2 = leb_u(data, j2)
                            ln, j2 = leb_u(data, j2)
                            names[idx] = data[j2:j2 + ln].decode('utf-8', 'replace')
                            j2 += ln
                    j = send
        i = end

    targets = [idx for idx, nm in names.items() if needle in nm]
    print('target matches:', [(t, names[t]) for t in targets[:5]])
    if not targets:
        sys.exit('no function name contains %r' % needle)
    pats = {t: b'\x10' + enc_leb(t) for t in targets}

    hits = []
    for idx, off, sz in code_entries:
        nm = names.get(idx, '')
        body = data[off:off + sz]
        for t, pat in pats.items():
            if pat in body:
                hits.append((idx, nm, names[t]))
                break
    print('%d function(s) call it directly' % len(hits))
    inits = [h for h in hits if 'GLOBAL__sub_I' in h[1] or 'global_var_init' in h[1]
             or 'global-ctors' in h[1] or 'static_initialization' in h[1]]
    for idx, nm, tgt in (inits or hits[:63]):
        print('  %d %s' % (idx, nm))
    if inits:
        print()
        print('STATIC INITIALIZER(S):')
        for idx, nm, tgt in inits:
            print('  ', nm)


if __name__ == '__main__':
    main()
