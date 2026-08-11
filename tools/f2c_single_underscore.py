#!/usr/bin/env python3
"""Match gfortran's external-name convention in f2c's output.

A Fortran symbol becomes a C symbol by appending an underscore -- `op_corio` ->
`op_corio_`. f2c appends a *second* one when the Fortran name already contains an
underscore, so it emits `op_corio__`. gfortran does not (that is -fsecond-underscore,
off by default), and CalculiX's C files are written against gfortran, so they call
`op_corio_` and the link comes up short.

A blanket `x__` -> `x_` rename would be wrong: for a Fortran name that genuinely ends
in an underscore, `foo_`, both compilers produce `foo__`. So the expected symbol is
derived from the Fortran source filenames (ccx is one routine per file) rather than
guessed from the C spelling. Only occurrences followed by `(` are touched -- that is a
call or a declaration; f2c's renamed *locals* are used as `x__[i]` or `&x__`.

Usage: f2c_single_underscore.py <dir-of-generated-.c> <dir-of-.f>
"""
import re
import sys
import pathlib


def renames(fortran_names):
    """Fortran base name -> (f2c spelling, gfortran spelling), for the ones that differ."""
    out = {}
    for n in fortran_names:
        if '_' in n and not n.endswith('_'):
            out[n + '__'] = n + '_'
    return out


def apply(text, table):
    def sub(m):
        return table.get(m.group(1), m.group(1)) + '('
    return re.sub(r'\b(\w+__)\s*\(', sub, text)


RE_UNIT = re.compile(
    r'^\s{6,}(?:[a-z]+\*?\d*\s+)?(?:subroutine|function)\s+(\w+)\s*\(', re.I | re.M)


def unit_names(fdir):
    """Every program unit defined under fdir.

    Not the filenames: a file may define a routine with a different name (iniran lives
    in ranuwh.f, arscnd in second.f), and keying on the filename silently misses those,
    leaving the definition double-underscored while its callers get renamed.
    """
    names = set()
    for p in sorted(fdir.glob('*.f')):
        names.add(p.stem)
        names |= set(RE_UNIT.findall(p.read_text(errors='replace')))
    return names


def main():
    cdir, fdir = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
    table = renames(unit_names(fdir))
    n = 0
    for p in sorted(cdir.glob('*.c')):
        t = p.read_text(errors='replace')
        new = apply(t, table)
        if new != t:
            p.write_text(new)
            n += 1
    print('renamed %d double-underscore externals across %d files' % (len(table), n))


def selftest():
    t = renames(['op_corio', 'plain', 'trailing_'])
    assert t == {'op_corio__': 'op_corio_'}, t
    src = 'void op_corio__(int *a);\nx = op_corio__(&b);\ny = arr__[i] + trailing__;\n'
    got = apply(src, t)
    assert 'void op_corio_(int *a);' in got and 'op_corio_(&b)' in got, got
    # a renamed local, and a name that really ends in _, must both survive untouched
    assert 'arr__[i]' in got and 'trailing__' in got, got
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        p = pathlib.Path(d) / 'ranuwh.f'
        p.write_text('      subroutine ranuwh(a)\n      end\n'
                     '      subroutine ini_ran(b)\n      end\n')
        got = unit_names(pathlib.Path(d))
    assert 'ini_ran' in got and 'ranuwh' in got, got   # not just the filename
    print('f2c_single_underscore selftest OK')


if __name__ == '__main__':
    selftest() if len(sys.argv) == 2 and sys.argv[1] == '--selftest' else main()
