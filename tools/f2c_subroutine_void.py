#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) Virtastic
"""Make f2c-translated Fortran SUBROUTINEs return void instead of int.

wasm is strictly typed: if one object declares `foo_` as returning void and another
defines it returning i32, wasm-ld resolves the call to a trapping stub (or, for the
definition, refuses to link outright). CalculiX hits this on every subroutine, because
CalculiX.h declares them `void` while f2c emits `/* Subroutine */ int foo_(...)`.

f2c marks subroutines -- and only subroutines -- with a `/* Subroutine */` comment, so
that marker cleanly separates them from real FUNCTIONs (whose return values matter and
are left alone). Inside a rewritten subroutine, f2c's `return 0;` becomes `return;`.

The rewrite is uniform apart from an explicit exclusion list, and it has to be: the
generated code must agree with itself, so rewriting only a subset is worse than not
rewriting at all. The exclusions are exactly the symbols defined OUTSIDE the generated
set -- libf2c's runtime (s_stop, s_copy, s_cat ...) and the hand-written C in bridge/ --
which f2c also spells "/* Subroutine */ int" but which genuinely do return int. That
list is derived from the built libraries rather than guessed; see build-ccx-weh.sh.

Usage: f2c_subroutine_void.py <dir-of-generated-.c> [--exclude-from <symbol-list>]
"""
import re
import sys
import pathlib

MARK = '/* Subroutine */ int '
RE_RETURN0 = re.compile(r'\breturn 0;')
RE_INT_DECL = re.compile(r'/\* Subroutine \*/ int (\w+)\(')
# a definition opens a body; an `extern` declaration ends in `;` and has none
RE_DEF = re.compile(r'^/\* Subroutine \*/ void ')


RE_DECL_START = re.compile(r'(extern\s+)?/\* Subroutine \*/ int\s')


def split_grouped_decls(text):
    """Give each declarator its own declaration.

    f2c groups externs together:

        extern /* Subroutine */ int exit_(integer *), nident_(integer *, ...);

    The return type belongs to the whole statement, so a per-symbol rewrite cannot
    touch one without the other -- and exit_ is libf2c's, so it must stay int, which
    would drag nident_ along with it and leave it mismatched against its own void
    definition. Splitting first makes the two independent.
    """
    out, i = [], 0
    while True:
        m = RE_DECL_START.search(text, i)
        if not m:
            out.append(text[i:])
            break
        # find the terminating ';' at paren depth 0
        # A declaration ends at ';' and never contains '{'. Without the brace check the
        # scan runs straight past a *definition* into its body and splits the commas of
        # a DATA initializer -- which is how dlaruv's 512-entry table got shredded.
        j, depth, bad = m.end(), 0, False
        while j < len(text):
            c = text[j]
            if c == '(':
                depth += 1
            elif c == ')':
                depth -= 1
            elif c == '{' and depth == 0:
                bad = True
                break
            elif c == ';' and depth == 0:
                break
            j += 1
        if bad:
            out.append(text[i:m.end()])
            i = m.end()
            continue
        if j >= len(text):
            out.append(text[i:])
            break
        decls = split_top(text[m.end():j])
        if len(decls) > 1:
            head = (m.group(1) or '') + '/* Subroutine */ int '
            out.append(text[i:m.start()])
            out.append(''.join('%s%s;\n' % (head, d.strip()) for d in decls))
        else:
            out.append(text[i:j + 1])
        i = j + 1
    return ''.join(out)


def split_top(s):
    parts, buf, depth = [], [], 0
    for ch in s:
        if ch == '(':
            depth += 1
        elif ch == ')':
            depth -= 1
        elif ch == ',' and depth == 0:
            parts.append(''.join(buf))
            buf = []
            continue
        buf.append(ch)
    if ''.join(buf).strip():
        parts.append(''.join(buf))
    return parts


def fix(text, keep_int=()):
    """keep_int: symbols that must go on returning int (defined outside this set)."""
    text = split_grouped_decls(text)
    out, depth, in_sub = [], 0, False
    for line in text.split('\n'):
        line = RE_INT_DECL.sub(
            lambda m: m.group(0) if m.group(1) in keep_int
            else '/* Subroutine */ void %s(' % m.group(1), line)
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
    keep_int = set()
    if '--exclude-from' in sys.argv:
        p = pathlib.Path(sys.argv[sys.argv.index('--exclude-from') + 1])
        if p.exists():
            keep_int = {l.strip() for l in p.read_text().split('\n') if l.strip()}
    n = 0
    for p in sorted(d.glob('*.c')):
        src = p.read_text(errors='replace')
        if MARK not in src:
            continue
        new = fix(src, keep_int)
        if new != src:
            p.write_text(new)
            n += 1
    print('rewrote %d generated files (%d symbols left returning int)' % (n, len(keep_int)))


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

    # libf2c's runtime is declared the same way but defined in the library returning
    # int; rewriting its declaration would break the link
    lib = ('extern /* Subroutine */ int s_stop(char *, ftnlen);\n'
           '/* Subroutine */ int mine_(void)\n{\n    s_stop("", 0);\n    return 0;\n}\n')
    g2 = fix(lib, {'s_stop'})
    assert 'int s_stop(' in g2, g2
    assert 'void mine_(' in g2, g2

    # a grouped declaration mixing an excluded symbol with a normal one: the excluded
    # one must keep int WITHOUT dragging its neighbour along
    grouped = ('    extern /* Subroutine */ int exit_(integer *), nident_(integer *,\n'
               '\t    integer *);\n')
    g3 = fix(grouped, {'exit_'})
    assert 'int exit_(integer *);' in g3, g3
    assert 'void nident_(' in g3, g3
    # a single declarator must survive unchanged apart from the rewrite
    g4 = fix('extern /* Subroutine */ int solo_(integer *);\n')
    assert g4.count('solo_') == 1 and 'void solo_(integer *);' in g4, g4
    # a definition followed by an initializer must not be treated as a declaration list
    dat = ('/* Subroutine */ int dlaruv_(integer *iseed)\n{\n'
           '    static integer mm[4] = { 494, 2637, 255, 2008 };\n    return 0;\n}\n')
    g5 = fix(dat)
    assert '{ 494, 2637, 255, 2008 }' in g5, g5
    assert 'void dlaruv_(' in g5, g5
    print('f2c_subroutine_void selftest OK')


if __name__ == '__main__':
    selftest() if len(sys.argv) == 2 and sys.argv[1] == '--selftest' else main()
