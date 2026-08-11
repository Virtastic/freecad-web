#!/usr/bin/env python3
"""Give each Fortran COMMON block exactly one definition across f2c's output.

f2c emits a COMMON block as a tentative definition -- `struct { ... } debug_;` -- in
every file that references it. The traditional common-symbol model merged those, but
clang defaults to -fno-common, which makes each one a hard definition and the link a
pile of duplicate symbols.

-fcommon looks like the one-line fix and is not: on the wasm target it crashes clang
outright in AsmPrinter::emitGlobalVariable (exit 133) for exactly the ARPACK files that
carry the big debug_/timing_ blocks. So the definitions are deduplicated here instead --
the first file holding a given block keeps it, every other copy becomes `extern`.

Usage: f2c_dedupe_commons.py <dir-of-generated-.c> [--extern name_,name_]
"""
import re
import sys
import pathlib

RE_COMMON = re.compile(r'(?m)^(struct\s*\{.*?\}\s*)(\w+_)(\s*;)', re.S)


def dedupe(texts, owned_elsewhere=()):
    """texts: dict path -> source. Returns dict of changed path -> new source.

    Names in owned_elsewhere are defined in another library that this one links
    against, so every copy here becomes extern -- otherwise each archive contributes
    its own definition and the two collide at link time.
    """
    owner = {n: None for n in owned_elsewhere}
    changed = {}
    for path in sorted(texts):
        text = texts[path]

        def repl(m):
            name = m.group(2)
            if owner.setdefault(name, path) == path:
                return m.group(0)
            return 'extern ' + m.group(1) + name + m.group(3)

        new = RE_COMMON.sub(repl, text)
        if new != text:
            changed[path] = new
    return changed


def main():
    d = pathlib.Path(sys.argv[1])
    ext = ()
    if '--extern' in sys.argv:
        ext = tuple(n for n in sys.argv[sys.argv.index('--extern') + 1].split(',') if n)
    texts = {p: p.read_text(errors='replace') for p in sorted(d.glob('*.c'))}
    changed = dedupe(texts, ext)
    for p, t in changed.items():
        p.write_text(t)
    print('deduplicated COMMON blocks in %d files' % len(changed))


def selftest():
    a = 'struct {\n    int logfil;\n} debug_;\n\n#define debug_1 debug_\n'
    b = 'struct {\n    int logfil;\n} debug_;\nvoid f_(void){}\n'
    out = dedupe({'a.c': a, 'b.c': b})
    assert 'a.c' not in out, 'first file must keep the definition'
    assert out['b.c'].startswith('extern struct'), out['b.c']
    assert '#define debug_1 debug_' in dedupe({'a.c': a, 'b.c': a})['b.c']
    # a block owned by another library must be extern in every file here
    out2 = dedupe({'a.c': a, 'b.c': b}, owned_elsewhere=('debug_',))
    assert out2['a.c'].startswith('extern struct'), out2['a.c']
    assert out2['b.c'].startswith('extern struct'), out2['b.c']
    print('f2c_dedupe_commons selftest OK')


if __name__ == '__main__':
    selftest() if len(sys.argv) == 2 and sys.argv[1] == '--selftest' else main()
