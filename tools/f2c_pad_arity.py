#!/usr/bin/env python3
"""Make every reference to a symbol agree on one argument count.

CalculiX calls a few of its own routines with more arguments than the routine declares
-- cload_ is called with 17 and defined with 13, xermsg_ with 8 and 5. gfortran does no
cross-file checking and on x86-64 the extra arguments land in registers the callee never
reads, so it works. wasm is strictly typed: the mismatch resolves to a stub that traps
the moment it is called.

Rather than pick a "correct" arity, everything is normalised to the widest one seen:
definitions and declarations gain ignored trailing parameters, and calls that pass fewer
gain null arguments. The callee cannot read them -- it never declared them -- so this
changes no behaviour that was defined to begin with.

Arities come from the wasm-ld log, so this describes what the linker actually saw
instead of a hand-maintained list.

Usage: f2c_pad_arity.py <dir-of-generated-.c> <wasm-ld-log>
"""
import re
import sys
import pathlib

RE_WARN = re.compile(
    r'function signature mismatch: (\w+)\n((?:>>> defined as \([^)]*\)[^\n]*\n?)+)')
RE_SIG = re.compile(r'>>> defined as \(([^)]*)\)')


def target_arities(log):
    """symbol -> widest argument count wasm-ld reported for it."""
    out = {}
    for m in RE_WARN.finditer(log):
        counts = []
        for sig in RE_SIG.findall(m.group(2)):
            sig = sig.strip()
            counts.append(len([a for a in sig.split(',') if a.strip()]) if sig else 0)
        if counts and max(counts) != min(counts):
            out[m.group(1)] = max(counts)
    return out


def match_paren(text, i):
    depth, quote = 0, None
    while i < len(text):
        c = text[i]
        if quote:
            if c == '\\':
                i += 2
                continue
            if c == quote:
                quote = None
        elif c in '"\'':
            quote = c
        elif c == '(':
            depth += 1
        elif c == ')':
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def split_top(s):
    parts, buf, depth, quote = [], [], 0, None
    for ch in s:
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in '"\'':
            quote = ch
        elif ch in '([':
            depth += 1
        elif ch in ')]':
            depth -= 1
        elif ch == ',' and depth == 0:
            parts.append(''.join(buf))
            buf = []
            continue
        buf.append(ch)
    if ''.join(buf).strip():
        parts.append(''.join(buf))
    return parts


def pad(text, arities):
    out, pos = [], 0
    for m in re.finditer(r'\b(\w+)\s*\(', text):
        if m.start() < pos:
            continue
        name = m.group(1)
        want = arities.get(name)
        if not want:
            continue
        open_i = m.end() - 1
        close = match_paren(text, open_i)
        if close < 0:
            continue
        inner = text[open_i + 1:close]
        args = split_top(inner)
        if len(args) >= want:
            continue
        after = text[close + 1:close + 40].lstrip()
        is_decl = bool(re.match(r'^[;{]', after)) and (
            '*' in inner or not inner.strip() or re.search(r'\b(integer|doublereal|char|ftnlen|void)\b', inner))
        filler = ('integer *fcweb_pad%d' if is_decl else '(integer *)0')
        extra = [filler % k if is_decl else filler for k in range(len(args), want)]
        out.append(text[pos:open_i + 1])
        out.append(','.join([a.strip() for a in args] + extra))
        pos = close
    out.append(text[pos:])
    return ''.join(out)


def main():
    d, log = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
    arities = target_arities(log.read_text(errors='replace'))
    if not arities:
        print('no arity mismatches to pad')
        return
    n = 0
    for p in sorted(d.glob('*.c')):
        t = p.read_text(errors='replace')
        if not any(name in t for name in arities):
            continue
        new = pad(t, arities)
        if new != t:
            p.write_text(new)
            n += 1
    print('padded %d symbols across %d files: %s'
          % (len(arities), n, ' '.join(sorted(arities))))


def selftest():
    log = ('wasm-ld: warning: function signature mismatch: cload_\n'
           '>>> defined as (i32, i32, i32) -> void in a.o\n'
           '>>> defined as (i32, i32) -> void in b.o\n'
           'wasm-ld: warning: function signature mismatch: same_\n'
           '>>> defined as (i32) -> void in a.o\n'
           '>>> defined as (i32) -> i32 in b.o\n')
    a = target_arities(log)
    assert a == {'cload_': 3}, a          # same_ differs in return type, not arity
    src = ('void cload_(integer *x, integer *y);\n'
           'void cload_(integer *x, integer *y)\n{\n}\n'
           'int f(void){ cload_(&p, &q); cload_(&p, &q, &r); }\n')
    got = pad(src, a)
    assert 'void cload_(integer *x,integer *y,integer *fcweb_pad2);' in got, got
    assert 'cload_(&p,&q,(integer *)0)' in got, got
    assert 'cload_(&p, &q, &r)' in got or 'cload_(&p,&q,&r)' in got, got
    print('f2c_pad_arity selftest OK')


if __name__ == '__main__':
    selftest() if len(sys.argv) == 2 and sys.argv[1] == '--selftest' else main()
