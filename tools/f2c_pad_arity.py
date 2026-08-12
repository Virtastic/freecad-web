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

The target arity comes primarily from each routine's own DEFINITION, which is the only
authoritative source. The wasm-ld log is merged in as a supplement because it reports
cases where the callers agree with each other but not with the definition -- and it is
not sufficient on its own: wasm-ld stayed silent about umat_compression_only_ (declared
with 28 in umat_main.c, defined with 30), which was enough to make the whole module fail
to instantiate.

Usage: f2c_pad_arity.py <dir-of-generated-.c> [wasm-ld-log] [--defs-also <dir>]
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



def arity_of(inner):
    """Parameter count of a C parameter list. `(void)` is zero parameters, not one --
    counting it as one made every call to closefile_() look one argument short."""
    args = split_top(inner)
    if len(args) == 1 and args[0].strip() == 'void':
        return []
    return args


def pad(text, arities, skip=()):
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
        args = arity_of(inner)
        if len(args) >= want:
            continue
        after = text[close + 1:close + 40].lstrip()
        # `skip` holds names DEFINED in this file. Their forward declaration must not be
        # padded (the definition's real types would conflict), but the definition itself
        # still has to grow when a caller passes more -- cload is declared with 13
        # arguments and called from temploadfem with 17.
        if name in skip and not after.startswith('{'):
            continue
        # Decide on what comes BEFORE the name, not on what is inside the parentheses:
        # a call like `inputerror_(inpc,iline,"*HCF%",(ftnlen)1)` contains the word
        # `ftnlen` and ends in `;` exactly like a declaration does, and padding it with
        # `integer *fcweb_pad6` puts a parameter declaration in an argument list.
        head = text[max(0, m.start() - 120):m.start()]
        head = re.split(r'[;{}]|\n\n', head)[-1]
        is_decl = bool(re.match(r'^[;{]', after)) and bool(
            re.search(r'\bextern\b', head)
            or re.match(r'^\s*(/\* Subroutine \*/\s*)?'
                        r'(void|int|integer|doublereal|logical|real|char|ftnlen|U_fp)'
                        r'[ \t\*]+$', head))
        filler = ('integer *fcweb_pad%d' if is_decl else '(integer *)0')
        extra = [filler % k if is_decl else filler for k in range(len(args), want)]
        out.append(text[pos:open_i + 1])
        out.append(','.join([a.strip() for a in args] + extra))
        pos = close
    out.append(text[pos:])
    return ''.join(out)


RE_DEF = re.compile(
    r'(?m)^(?:/\* Subroutine \*/ )?(?:void|int|doublereal|integer|logical|real|char)'
    r'[ \t\*]+(\w+_)\s*\(')


def definition_arities(dirs):
    """name -> parameter count, taken from the definition (the authoritative source)."""
    out = {}
    for d in dirs:
        for p in sorted(pathlib.Path(d).glob('*.c')):
            t = p.read_text(errors='replace')
            for m in RE_DEF.finditer(t):
                close = match_paren(t, m.end() - 1)
                if close < 0:
                    continue
                if not t[close + 1:close + 60].lstrip().startswith('{'):
                    continue                       # a declaration, not a definition
                out[m.group(1)] = len(arity_of(t[m.end():close]))
    return out



RE_FORTRAN_MACRO = re.compile(r'\bFORTRAN\s*\(\s*(\w+)\s*,')


def macro_called(dirs):
    """Names ccx's hand-written C calls through the FORTRAN() macro.

    Those call sites are in the shared source tree and are not rewritten here, so their
    arity cannot be changed -- the definition has to stay as it is, whatever a recorded
    link log says. `cload` is the opposite case: nothing in the C tree calls it, so the
    log's larger arity is real (temploadfem passes 17 to a 13-argument declaration) and
    padding the definition is what keeps wasm-ld from making it a trapping stub.
    """
    out = set()
    for d in dirs:
        for p in sorted(pathlib.Path(d).glob('*.c')):
            out |= {n + '_' for n in RE_FORTRAN_MACRO.findall(p.read_text(errors='replace'))}
    return out


def main():
    d = pathlib.Path(sys.argv[1])
    extra = []
    if '--defs-also' in sys.argv:
        extra = [sys.argv[sys.argv.index('--defs-also') + 1]]
    arities = definition_arities([d] + extra)
    # The log only fills in routines with no definition anywhere. Where a definition
    # exists it wins, even over the recorded link log: `closefile` takes no arguments,
    # ccx's C calls it through the FORTRAN() macro (which this tool cannot rewrite), and
    # trusting the log's arity of 1 produced `closefile_((integer *)0)`.
    pinned = macro_called(extra)
    for a in sys.argv[2:]:
        p = pathlib.Path(a)
        if p.is_file():
            for name, n in target_arities(p.read_text(errors='replace')).items():
                if name in pinned:
                    continue
                arities[name] = max(arities.get(name, 0), n)
    if not arities:
        print('no arity mismatches to pad')
        return
    n = 0
    for p in sorted(d.glob('*.c')):
        t = p.read_text(errors='replace')
        if not any(name in t for name in arities):
            continue
        # A routine DEFINED in this file already has authoritative argument types; f2c
        # writes an argument-less forward declaration for it, and padding that with
        # `integer *` conflicts with a definition taking `doublereal *` (fform_ in
        # calcview, df_ in subspace, f_m_ in moehring).
        here = set(RE_DEF.findall(t))
        new = pad(t, arities, skip=here)
        if new != t:
            p.write_text(new)
            n += 1
    print('normalised arity for %d symbols across %d files' % (len(arities), n))


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
    # a call whose arguments merely mention a type is still a call
    call = 'void f(void){ inputerror_(a,b,"*X%",(ftnlen)1,(ftnlen)5); }'
    padded = pad(call, {'inputerror_': 6})
    assert '(integer *)0' in padded and 'fcweb_pad' not in padded, padded
    same = ('doublereal fform_();\n'
            'doublereal fform_(doublereal *x, doublereal *y){ return *x; }\n')
    got2 = pad(same, {'fform_': 4}, skip=set(RE_DEF.findall(same)))
    assert 'doublereal fform_();' in got2, 'forward declaration untouched: ' + got2
    assert 'doublereal *y,integer *fcweb_pad2,integer *fcweb_pad3)' in got2, got2
    grow = 'void cload_(integer *a);\nvoid cload_(integer *a){ }\n'
    g = pad(grow, {'cload_': 2}, skip={'cload_'})
    assert g.count('fcweb_pad1') == 1 and 'cload_(integer *a);' in g, g
    assert arity_of('void') == [] and len(arity_of('integer *a')) == 1
    assert RE_FORTRAN_MACRO.findall('  FORTRAN(closefile,());') == ['closefile']
    assert definition_arities.__doc__
    assert 'cload_(&p, &q, &r)' in got or 'cload_(&p,&q,&r)' in got, got
    import tempfile as _tf
    with _tf.TemporaryDirectory() as td:
        (pathlib.Path(td) / 'z.c').write_text(
            'void umat_compression_only_(int *a, int *b, int *c)\n{\n}\n'
            'void other_(int *a);\n')
        da = definition_arities([td])
    assert da['umat_compression_only_'] == 3, da
    assert 'other_' not in da, 'declarations are not definitions'
    print('f2c_pad_arity selftest OK')


if __name__ == '__main__':
    selftest() if len(sys.argv) == 2 and sys.argv[1] == '--selftest' else main()
