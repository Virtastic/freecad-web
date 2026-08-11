#!/usr/bin/env python3
"""Drop f2c's hidden CHARACTER-length arguments where CalculiX's C code omits them.

For `character` dummy arguments, f2c (like gfortran) appends a hidden `ftnlen` parameter
per argument. CalculiX's C callers do not pass them. Natively that is harmless -- the
callee reads a garbage register it never uses -- but wasm is strictly typed, so wasm-ld
resolves the arity mismatch to a stub that traps the moment it is called.

Only lengths the callee never reads are removed, and they are removed consistently:
from the definition, from every `extern` declaration, and from every call site in the
generated code. Library calls (s_cmp, s_copy, do_fio ...) genuinely need their lengths
and are untouched, because only names DEFINED in the generated set are considered.

Usage: f2c_strip_ftnlen.py <dir-of-generated-.c>
"""
import re
import sys
import pathlib

RE_DEFHEAD = re.compile(r'(?m)^(?:/\* Subroutine \*/ )?[A-Za-z_][A-Za-z_0-9 ]*?\*?\s*(\w+)_\(')
RE_CALLSITE = re.compile(r'\b(\w+)_\(')


def match_delim(text, open_idx, opener='(', closer=')'):
    """Index just past the delimiter matching the one at open_idx, or -1."""
    depth, i, quote = 0, open_idx, None
    while i < len(text):
        ch = text[i]
        if quote:
            if ch == '\\':
                i += 2
                continue
            if ch == quote:
                quote = None
        elif ch in '"\'':
            quote = ch
        elif ch == opener:
            depth += 1
        elif ch == closer:
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return -1


def match_paren(text, open_idx):
    return match_delim(text, open_idx, '(', ')')


def split_args(text):
    out, buf, depth, quote = [], [], 0, None
    for ch in text:
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
            out.append(''.join(buf))
            buf = []
            continue
        buf.append(ch)
    if ''.join(buf).strip():
        out.append(''.join(buf))
    return out


def find_definitions(text):
    """Yield (name, params_text, body_text) for every function defined in `text`."""
    for m in RE_DEFHEAD.finditer(text):
        open_idx = m.end() - 1
        close = match_paren(text, open_idx)
        if close < 0:
            continue
        rest = text[close:]
        stripped = rest.lstrip()
        if not stripped.startswith('{'):
            continue                              # a declaration, not a definition
        brace = close + (len(rest) - len(stripped))
        end = match_delim(text, brace, '{', '}')
        yield m.group(1), text[open_idx + 1:close - 1], text[brace:end if end > 0 else len(text)]


def strippable_counts(texts):
    """name -> number of trailing hidden-length params the body never reads."""
    counts = {}
    for text in texts:
        for name, params, body in find_definitions(text):
            args = split_args(params)
            k = 0
            for a in reversed(args):
                mm = re.match(r'^\s*ftnlen\s+(\w+)\s*$', a)
                if not mm:
                    break
                if len(re.findall(r'\b%s\b' % mm.group(1), body)) > 0:
                    break                          # the callee actually reads it
                k += 1
            if k:
                counts[name] = min(counts.get(name, k), k)
    return counts


def rewrite(text, counts):
    out, pos = [], 0
    for m in RE_CALLSITE.finditer(text):
        if m.start() < pos:
            continue
        name = m.group(1)
        k = counts.get(name)
        if not k:
            continue
        open_idx = m.end() - 1
        close = match_paren(text, open_idx)
        if close < 0:
            continue
        args = split_args(text[open_idx + 1:close - 1])
        # only drop trailing args that really are lengths, in either spelling
        drop = 0
        for a in reversed(args):
            if drop >= k:
                break
            # f2c line-wraps long calls, so a cast can arrive as "(\n\t    ftnlen)1";
            # compare with whitespace removed or the wrapped ones get missed, which
            # would strip a call's args inconsistently with its declaration.
            compact = re.sub(r'\s+', '', a)
            # three spellings reach a call site: a bare `ftnlen` in a declaration, an
            # `(ftnlen)N` cast, and a forwarded length variable `x_len` when the caller
            # is itself passing one of its own hidden arguments through.
            if (re.match(r'^ftnlen\w*$', compact) or compact.startswith('(ftnlen)')
                    or re.match(r'^\w+_len$', compact)):
                drop += 1
            else:
                break
        if not drop:
            continue
        out.append(text[pos:open_idx + 1])
        out.append(','.join(args[:len(args) - drop]))
        out.append(')')
        pos = close
    out.append(text[pos:])
    return ''.join(out)


def arg(flag):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else None


def main():
    d = pathlib.Path(sys.argv[1])
    files = sorted(d.glob('*.c'))
    texts = {p: p.read_text(errors='replace') for p in files}
    counts = strippable_counts(texts.values())
    # lengths another library already stripped. Without this the two disagree: ARPACK
    # strips lsame_'s two hidden lengths, ccx's dgesv keeps passing them, and the call
    # becomes a trapping stub.
    also = arg('--also')
    if also and pathlib.Path(also).exists():
        for l in pathlib.Path(also).read_text().split('\n'):
            if l.startswith('strip '):
                _, name, k = l.split()
                counts.setdefault(name, int(k))
    n = 0
    for p, t in texts.items():
        new = rewrite(t, counts)
        if new != t:
            p.write_text(new)
            n += 1
    emit = arg('--emit')
    if emit:
        with open(emit, 'a') as f:
            for name, k in sorted(counts.items()):
                f.write('strip %s %d\n' % (name, k))
    print('stripped hidden lengths from %d symbols across %d files' % (len(counts), n))


def selftest():
    src = ('/* Subroutine */ void foo_(integer *n, char *s, ftnlen s_len)\n'
           '{\n    *n = 1;\n    return;\n}\n'
           'extern /* Subroutine */ void foo_(integer *, char *, ftnlen);\n'
           '/* Subroutine */ void bar_(char *s, ftnlen s_len)\n'
           '{\n    foo_(&i, s, (ftnlen)80);\n    x = s_cmp(a, b, (ftnlen)3, (ftnlen)4);\n'
           '    y = s_len;\n    return;\n}\n')
    counts = strippable_counts([src])
    assert counts.get('foo') == 1, counts
    assert 'bar' not in counts, counts          # bar reads its own length
    got = rewrite(src, counts)
    assert 'void foo_(integer *n, char *s)' in got, got
    assert 'foo_(&i, s)' in got, got
    assert 's_cmp(a, b, (ftnlen)3, (ftnlen)4)' in got, got   # library call untouched
    # a call f2c wrapped across lines must strip identically to an unwrapped one
    wrapped = ('/* Subroutine */ void baz_(char *s, ftnlen s_len)\n{\n    return;\n}\n'
               'void q_(void)\n{\n    baz_(s, (\n\t    ftnlen)1);\n}\n')
    c2 = strippable_counts([wrapped])
    assert c2.get('baz') == 1, c2
    assert 'baz_(s)' in rewrite(wrapped, c2), rewrite(wrapped, c2)
    # a body whose parens outnumber its braces must still be scanned to its real end,
    # or a length used late in the function looks unused and gets wrongly stripped
    late = ('/* Subroutine */ void lt_(char *s, ftnlen s_len)\n{\n'
            '    if ((a) && (b)) { x = (c); }\n    y = s_len;\n    return;\n}\n')
    assert 'lt' not in strippable_counts([late]), strippable_counts([late])
    # a forwarded length variable must strip too, or one file ends up calling the same
    # symbol with two different arities
    fwd = ('/* Subroutine */ void h_(char *m, ftnlen m_len)\n{\n    return;\n}\n'
           '/* Subroutine */ void c_(char *messg, ftnlen messg_len)\n{\n'
           '    h_(" ", (ftnlen)1);\n    h_(messg, messg_len);\n    return;\n}\n')
    cf = strippable_counts([fwd])
    got_f = rewrite(fwd, cf)
    assert 'h_(" ")' in got_f and 'h_(messg)' in got_f, got_f
    print('f2c_strip_ftnlen selftest OK')


if __name__ == '__main__':
    selftest() if len(sys.argv) == 2 and sys.argv[1] == '--selftest' else main()
