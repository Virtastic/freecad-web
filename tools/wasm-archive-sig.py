# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) Virtastic
"""Report a symbol's signature on both sides of a static-library boundary.

    python tools/wasm-archive-sig.py XML_GetCurrentByteIndex deps/wasm/lib/*.a

For each archive, prints every member that defines or references the symbol, with the
function type wasm-ld will see. A DEFINED entry is the provider; an UNDEFINED one is a
consumer, and its type is what that translation unit was compiled to expect.

WHY

wasm is strictly typed and wasm-ld will not silently reconcile a caller that expects
(i32) -> i64 with a definition of (i32) -> i32. With ERROR_ON_UNDEFINED_SYMBOLS=0 it
resolves the mismatch to a stub that traps, so the failure is not a link error but

    RuntimeError: unreachable
      at vtkXMLParser::GetXMLByteIndex()

on the first .vtu the application reads -- which is what made the shipped FEMExample crash
the engine. The cause was expat's XML_Index: 64-bit where XML_LARGE_SIZE is defined,
`long` (32-bit on wasm32) where it is not, with the vendored library and its consumers
disagreeing.

Reading the archives answers it directly, without a two-hour link: if the provider and
every consumer agree on the type, there is nothing for wasm-ld to stub.

Nothing here is emscripten-specific -- it parses the ar container, each member's wasm
object sections, and the `linking` custom section's symbol table, which is where a
relocatable object records its names.
"""
import glob
import io
import sys

VALTYPE = {0x7F: 'i32', 0x7E: 'i64', 0x7D: 'f32', 0x7C: 'f64',
           0x7B: 'v128', 0x70: 'funcref', 0x6F: 'externref'}

WASM_SYM_UNDEFINED = 0x10
WASM_SYM_EXPLICIT_NAME = 0x40
SYMTAB = 8


def leb_u(b, i):
    r = s = 0
    while True:
        x = b[i]
        i += 1
        r |= (x & 0x7F) << s
        if not x & 0x80:
            return r, i
        s += 7


def ar_members(data):
    """(name, bytes) for each member of a System V / GNU ar archive."""
    if not data.startswith(b'!<arch>\n'):
        return
    i = 8
    longnames = b''
    while i + 60 <= len(data):
        hdr = data[i:i + 60]
        name = hdr[0:16].decode('ascii', 'replace').strip()
        try:
            size = int(hdr[48:58].decode('ascii', 'replace').strip())
        except ValueError:
            return
        body = data[i + 60:i + 60 + size]
        i += 60 + size + (size & 1)
        if name == '//':
            longnames = body
            continue
        if name.startswith('/') and name[1:].isdigit():
            off = int(name[1:])
            end = longnames.find(b'/', off)
            name = longnames[off:end].decode('ascii', 'replace')
        name = name.rstrip('/')
        if name in ('', '/', '__.SYMDEF'):
            continue
        yield name, body


def parse_object(d):
    """(types, import_func_types, defined_func_types, symbols) for one wasm object."""
    types, imports, funcs, syms = [], [], [], []
    import_names = []       # field name per imported function, in order
    if d[:4] != b'\0asm':
        return types, imports, funcs, syms
    i = 8
    while i < len(d):
        sec = d[i]
        i += 1
        size, i = leb_u(d, i)
        end, j = i + size, i
        if sec == 1:                                   # type
            cnt, j = leb_u(d, j)
            for _ in range(cnt):
                j += 1                                 # 0x60
                np, j = leb_u(d, j)
                params = [VALTYPE.get(x, hex(x)) for x in d[j:j + np]]
                j += np
                nr, j = leb_u(d, j)
                results = [VALTYPE.get(x, hex(x)) for x in d[j:j + nr]]
                j += nr
                types.append((params, results))
        elif sec == 2:                                 # import
            cnt, j = leb_u(d, j)
            for _ in range(cnt):
                ml, j = leb_u(d, j)
                j += ml
                nl, j = leb_u(d, j)
                field = d[j:j + nl].decode('utf-8', 'replace')
                j += nl
                kind = d[j]; j += 1
                if kind == 0:                          # func: typeidx
                    t, j = leb_u(d, j)
                    imports.append(t)
                    # An UNDEFINED function symbol carries no name of its own unless
                    # WASM_SYM_EXPLICIT_NAME is set -- it takes it from here. Without this
                    # every consumer of a symbol is invisible, which makes a one-sided
                    # report look like agreement.
                    import_names.append(field)
                elif kind == 1:                        # table: reftype + limits
                    j += 1
                    fl, j = leb_u(d, j)
                    _, j = leb_u(d, j)                 # min
                    if fl & 1:
                        _, j = leb_u(d, j)             # max
                elif kind == 2:                        # memory: limits
                    fl, j = leb_u(d, j)
                    _, j = leb_u(d, j)                 # min
                    if fl & 1:
                        _, j = leb_u(d, j)             # max
                elif kind == 3:                        # global: valtype + mut
                    j += 2
                elif kind == 4:                        # tag: attribute + typeidx
                    j += 1                             # -fwasm-exceptions imports these
                    _, j = leb_u(d, j)
                else:
                    raise ValueError('unknown import kind %d' % kind)
        elif sec == 3:                                 # function
            cnt, j = leb_u(d, j)
            for _ in range(cnt):
                t, j = leb_u(d, j)
                funcs.append(t)
        elif sec == 0:                                 # custom
            nl, j = leb_u(d, j)
            nm = d[j:j + nl]; j += nl
            if nm == b'linking':
                _, j = leb_u(d, j)                     # version
                while j < end:
                    sub = d[j]; j += 1
                    ssz, j = leb_u(d, j)
                    sub_end = j + ssz
                    if sub == SYMTAB:
                        cnt, j = leb_u(d, j)
                        for _ in range(cnt):
                            kind = d[j]; j += 1
                            flags, j = leb_u(d, j)
                            if kind == 0:              # function
                                idx, j = leb_u(d, j)
                                name = None
                                if not (flags & WASM_SYM_UNDEFINED) or (flags & WASM_SYM_EXPLICIT_NAME):
                                    ln, j = leb_u(d, j)
                                    name = d[j:j + ln].decode('utf-8', 'replace'); j += ln
                                undef = bool(flags & WASM_SYM_UNDEFINED)
                                if name is None and idx < len(import_names):
                                    name = import_names[idx]
                                syms.append((name, idx, undef))
                            elif kind == 1:            # data
                                ln, j = leb_u(d, j)
                                j += ln
                                if not (flags & WASM_SYM_UNDEFINED):
                                    _, j = leb_u(d, j)
                                    _, j = leb_u(d, j)
                                    _, j = leb_u(d, j)
                            else:
                                idx, j = leb_u(d, j)
                                if not (flags & WASM_SYM_UNDEFINED) or (flags & WASM_SYM_EXPLICIT_NAME):
                                    ln, j = leb_u(d, j)
                                    j += ln
                    j = sub_end
        i = end
    return types, imports, funcs, syms


def sig_of(types, imports, funcs, idx):
    if idx < len(imports):
        t = imports[idx]
    else:
        k = idx - len(imports)
        if k >= len(funcs):
            return None
        t = funcs[k]
    if t >= len(types):
        return None
    params, results = types[t]
    return '(%s) -> %s' % (', '.join(params) or '', ', '.join(results) or 'void')


def main():
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    want = sys.argv[1]
    paths = []
    for pat in sys.argv[2:]:
        paths.extend(sorted(glob.glob(pat)) or [pat])

    seen = {}
    for path in paths:
        try:
            data = io.open(path, 'rb').read()
        except OSError as e:
            print('  %s: %s' % (path, e))
            continue
        for member, body in ar_members(data):
            types, imports, funcs, syms = parse_object(body)
            for name, idx, undef in syms:
                if name != want:
                    continue
                sig = sig_of(types, imports, funcs, idx) or '(unknown)'
                kind = 'UNDEFINED (consumer)' if undef else 'DEFINED   (provider)'
                print('  %-28s %-22s %s  %s' % (path.split('/')[-1], member, kind, sig))
                seen.setdefault(sig, set()).add(kind.split()[0])

    if not seen:
        print('  %s: not mentioned in any of those archives' % want)
        return 0
    if len(seen) == 1:
        sig = next(iter(seen))
        print('\n  one signature everywhere: %s -- nothing for wasm-ld to reconcile' % sig)
        return 0
    print('\n::error::%s has %d different signatures across these archives: %s'
          % (want, len(seen), ' vs '.join(sorted(seen))))
    print('        wasm-ld resolves that to a stub that traps, and the failure surfaces')
    print('        as "RuntimeError: unreachable" at the first call, not as a link error.')
    return 1


if __name__ == '__main__':
    sys.exit(main())
