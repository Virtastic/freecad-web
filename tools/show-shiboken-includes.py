"""Print how shiboken decides which clang builtin include directory to inject.

    python tools/show-shiboken-includes.py deps/src/pyside-setup

Diagnostic only -- it changes nothing.

WHY: shiboken puts a clang builtins directory ahead of everything the compiler reports,
and that directory's <stddef.h> beats libc++'s, which breaks every header after <cstddef>:

    <cstddef> tried including <stddef.h> but didn't find libc++'s <stddef.h>
    error: unknown type name 'nullptr_t'    (x125, all downstream)

Everything tried to outrank it has failed, and each attempt cost a full CI round:

  * -resource-dir=<em++'s>        no effect; the injected -I is separate from the
                                  resource dir
  * -nobuiltininc                 removed clang's OWN builtins (the last entry), not
                                  the injected one
  * libclang 17 / 19 / 20         identical 126 errors -- the version was never the issue
  * --include-paths=<libc++>:...  passed FIRST on the command line, searched EIGHTH:
                                  clang drops a normal include dir that duplicates a
                                  system dir and keeps the system position
  * -isystem<libc++>              still after it: shiboken assembles its own arguments
                                  before the --clang-option ones are appended

So the injection has to be changed where it is made. This prints the code that makes it,
so the patch is written against what is actually there rather than against a guess -- the
same approach that turned the include-order question from six blind rounds into one
`-v` run.
"""
import io
import os
import re
import sys

CANDIDATES = [
    'sources/shiboken6/ApiExtractor/clangparser/compilersupport.cpp',
    'sources/shiboken6/ApiExtractor/clangparser/compilersupport.h',
]

# The words worth seeing: anything that builds an include list, names a builtins/resource
# directory, or shells out to the compiler to ask.
PATTERNS = [
    r'builtin',
    r'BuiltIn',
    r'resource',
    r'clangBuiltin',
    r'CLANG_INSTALL_DIR',
    r'LLVM_INSTALL_DIR',
    r'-isystem',
    r'"-I"',
    r'includePaths',
    r'gppInternalIncludePaths',
    r'clangOptions',
    r'compilerPath',
]


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    root = sys.argv[1]
    rx = re.compile('|'.join(PATTERNS))
    found_any = False
    for rel in CANDIDATES:
        path = os.path.join(root, rel)
        if not os.path.exists(path):
            print('  (absent) %s' % rel)
            continue
        found_any = True
        print('=== %s' % rel)
        lines = io.open(path, encoding='utf-8', errors='replace').read().split('\n')
        shown = set()
        for i, line in enumerate(lines):
            if not rx.search(line):
                continue
            # a little context, deduplicated, so functions read as functions
            for n in range(max(0, i - 4), min(len(lines), i + 5)):
                if n in shown:
                    continue
                shown.add(n)
                mark = '>' if n == i else ' '
                print('%s%5d: %s' % (mark, n + 1, lines[n].rstrip()[:110]))
            print('       ---')
    if not found_any:
        sys.exit('none of the candidate sources exist under %s' % root)


if __name__ == '__main__':
    main()
