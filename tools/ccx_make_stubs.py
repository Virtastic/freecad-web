#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) Virtastic
"""Emit a Fortran stub for every CalculiX routine f2c cannot translate.

Some of ccx's F90 has no FORTRAN 77 spelling -- chiefly automatic arrays sized by a
mesh-level quantity (`real*8 x(neq(2))`), where no fixed bound is defensible. Those
files never reach the linker, and chasing the resulting undefined symbols one relink at
a time does not converge: resolving one pulls new archive members in, which reference
more of them.

So the gap is closed in one step. Every routine in an unconverted file gets a stub with
the *same signature*, whose body calls ccxstb() and aborts. Writing the stubs in Fortran
rather than C is what makes the arity right for free: they go through f2c and the same
ABI passes as everything else, so the hidden CHARACTER-length arguments are added and
removed consistently on both sides. Hand-written C stubs would have to guess.

Aborting is deliberate. These are solver routines; returning would mean reporting
stresses computed without them.

Usage: ccx_make_stubs.py <unconverted-list> <src-dir> <out-dir>
"""
import re
import sys
import pathlib

# The type may be two words ("double precision function d1mach(i)"); matching only a
# single token silently skips those units, and the routine then has no definition at all.
RE_UNIT = re.compile(
    r'^\s{6,}(?:(?P<type>(?:double\s+(?:precision|complex)|[a-z]+\*?\s*\d*))\s+)?'
    r'(?P<kind>subroutine|function)\s+(?P<name>\w+)\s*\(',
    re.I)
RE_CHAR_DECL = re.compile(r'^\s{6,}character\s*(\*\s*\d+)?\s+(.*)$', re.I)


def logical_lines(text):
    """Join fixed-form continuations into whole statements."""
    out = []
    for raw in text.split('\n'):
        if not raw.strip() or raw[:1] in 'cC*!':
            continue
        if len(raw) > 5 and raw[5] not in ' 0' and out:
            out[-1] += raw[6:].rstrip()
        else:
            out.append(raw.rstrip())
    return out


def split_args(text):
    parts, buf, depth = [], [], 0
    for ch in text:
        if ch == '(':
            depth += 1
        elif ch == ')':
            depth -= 1
            if depth < 0:
                break
        if ch == ',' and depth == 0:
            parts.append(''.join(buf).strip())
            buf = []
            continue
        buf.append(ch)
    if ''.join(buf).strip():
        parts.append(''.join(buf).strip())
    return [p for p in parts if p]


def char_decls(lines, args):
    """Reproduce CHARACTER declarations, restricted to dummy arguments.

    They must be kept: f2c appends a hidden length per character argument, and a stub
    that omitted them would have a different arity from the callers.
    """
    lower = {a.lower() for a in args}
    out = []
    for l in lines:
        m = RE_CHAR_DECL.match(l)
        if not m:
            continue
        star = (m.group(1) or '').replace(' ', '')
        keep = [e for e in split_args(m.group(2))
                if re.sub(r'\(.*', '', e).strip().lower() in lower]
        if keep:
            out.append('      character%s %s' % (star, ','.join(keep)))
    return out


def units(text):
    """Yield (kind, type, name, args, char_decl_lines) per program unit in a file."""
    lines = logical_lines(text)
    for i, l in enumerate(lines):
        m = RE_UNIT.match(l)
        if not m:
            continue
        args = split_args(l[l.index('(') + 1:])
        body = lines[i + 1:]
        yield (m.group('kind').lower(), (m.group('type') or '').lower(),
               m.group('name'), args, char_decls(body, args))


def emit(kind, typ, name, args, decls):
    head = '      %s %s' % (kind, name) if not typ else '      %s %s %s' % (typ, kind, name)
    # always parenthesised: "function f" with no arg list is not a function at all --
    # f2c reads it as a main program and the symbol never appears
    out = wrap(head + '(' + ','.join(args) + ')')
    out += decls
    if kind == 'function':
        out.append('      %s=0' % name)
    out.append("      call ccxstb('%s')" % name[:24])
    out.append('      end')
    return out


def wrap(stmt):
    """Break a statement across fixed-form continuation lines at column 72."""
    out = []
    while len(stmt) > 72:
        cut = stmt.rfind(',', 0, 72)
        if cut <= 6:
            break
        out.append(stmt[:cut + 1])
        stmt = '     &' + stmt[cut + 1:]
    out.append(stmt)
    return out


def main():
    listing, src, out = (pathlib.Path(a) for a in sys.argv[1:4])
    out.mkdir(parents=True, exist_ok=True)
    names, n = [], 0
    for line in listing.read_text().split('\n'):
        f = line.strip()
        if not f.endswith('.f'):
            continue
        p = src / f
        if not p.exists():
            continue
        body = []
        for u in units(p.read_text(errors='replace')):
            body += emit(*u)
            names.append(u[2])
        if body:
            (out / f).write_text('\n'.join(body) + '\n')
            n += 1
    print('generated %d stub files covering %d routines' % (n, len(names)))


def selftest():
    src = ('      subroutine zienzhu(a,lakon,b)\n'
           '      character*8 lakon(*)\n'
           '      real*8 x(neq(2))\n'
           '      x(1)=a\n'
           '      end\n')
    (kind, typ, name, args, decls), = units(src)
    assert (kind, name, args) == ('subroutine', 'zienzhu', ['a', 'lakon', 'b']), (kind, name, args)
    assert decls == ['      character*8 lakon(*)'], decls
    got = '\n'.join(emit(kind, typ, name, args, decls))
    assert 'subroutine zienzhu(a,lakon,b)' in got
    assert 'character*8 lakon(*)' in got            # hidden length preserved
    assert "call ccxstb('zienzhu')" in got
    assert 'x(neq(2))' not in got                   # the untranslatable local is gone
    for l in got.split('\n'):
        assert len(l) <= 72, repr(l)
    # a zero-argument function must still be emitted with parentheses
    z, = units('      real*8 function ranuwh()\n      end\n')
    gz = '\n'.join(emit(*z))
    assert 'function ranuwh()' in gz, gz
    assert 'ranuwh=0' in gz, gz
    # a two-word type must be recognised
    d, = units('      double precision function d1mach(i)\n      end\n')
    assert d[2] == 'd1mach' and d[0] == 'function', d
    assert 'double precision function d1mach(i)' in '\n'.join(emit(*d)), emit(*d)
    # ccx is not uniformly indented: some files start the statement in column 8
    sev, = units('       subroutine pk_cdi_rl(a,b)\n      end\n')
    assert sev[2] == 'pk_cdi_rl', sev
    print('ccx_make_stubs selftest OK')


if __name__ == '__main__':
    selftest() if len(sys.argv) == 2 and sys.argv[1] == '--selftest' else main()
