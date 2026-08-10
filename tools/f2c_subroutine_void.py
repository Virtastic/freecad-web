#!/usr/bin/env python3
"""Make f2c-translated Fortran SUBROUTINEs return void instead of int.

wasm is strictly typed: if one object declares `foo_` as returning void and another
defines it returning i32, wasm-ld resolves the call to a trapping stub (or, for the
definition, refuses to link outright). CalculiX hits this on every subroutine, because
CalculiX.h declares them `void` while f2c emits `/* Subroutine */ int foo_(...)`.

f2c marks subroutines -- and only subroutines -- with a `/* Subroutine */` comment, so
that marker cleanly separates them from real FUNCTIONs (whose return values matter and
are left alone). Inside a rewritten subroutine, f2c's `return 0;` becomes `return;`.

Usage: f2c_subroutine_void.py <dir-of-generated-.c>
"""
import re
import sys
import pathlib

MARK = '/* Subroutine */ int '
RE_RETURN0 = re.compile(r'\breturn 0;')
# a definition opens a body; an `extern` declaration ends in `;` and has none
RE_DEF = re.compile(r'^/\* Subroutine \*/ void ')


def fix(text):
    out, depth, in_sub = [], 0, False
    for line in text.split('\n'):
        line = line.replace(MARK, '/* Subroutine */ void ')
        if not in_sub and RE_DEF.match(line) and not line.rstrip().endswith(';'):
            in_sub, depth = True, 0
        if in_sub:
            line = RE_RETURN0.sub('return;', line)
            depth += line.count('{') - line.count('}')
            if depth <= 0 and '}' in line:
                in_sub = False
        out.append(line)
    return '\n'.join(out)


def main():
    d = pathlib.Path(sys.argv[1])
    n = 0
    for p in sorted(d.glob('*.c')):
        src = p.read_text(errors='replace')
        if MARK not in src:
            continue
        p.write_text(fix(src))
        n += 1
    print('rewrote %d generated files' % n)


def selftest():
    src = ('/* Subroutine */ int bar_(void);\n'
           '/* Subroutine */ int foo_(integer *n)\n{\n'
           '    if (*n) {\n\treturn 0;\n    }\n    return 0;\n}\n'
           'doublereal baz_(void)\n{\n    return 0;\n}\n')
    got = fix(src)
    assert '/* Subroutine */ void bar_(void);' in got
    assert 'int foo_' not in got and 'return 0;' not in got.split('doublereal')[0]
    # a real FUNCTION keeps both its type and its value
    assert 'doublereal baz_' in got and 'return 0;' in got.split('doublereal')[1]
    print('f2c_subroutine_void selftest OK')


if __name__ == '__main__':
    selftest() if len(sys.argv) == 2 and sys.argv[1] == '--selftest' else main()
