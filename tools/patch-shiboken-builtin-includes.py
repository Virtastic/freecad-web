"""Let shiboken skip injecting clang's builtin include directory.

    python tools/patch-shiboken-builtin-includes.py deps/src/pyside-setup

Makes appendClangBuiltinIncludes() return immediately. Unconditional, because the
generator runs through a generated wrapper script that does not pass the environment
through -- an env-gated check was added first and never fired.

WHY

shiboken puts a clang builtins directory ahead of every path the compiler reports:

    qt.shiboken: CLANG v0.64, builtins includes directory: /usr/lib/llvm-21/lib/clang/21/include

That directory's <stddef.h> is then found before libc++'s own, and libc++ refuses:

    <cstddef> tried including <stddef.h> but didn't find libc++'s <stddef.h> header.
    ... you are probably using compiler flags that make that not be the case
    error: unknown type name 'nullptr_t'      (x125, every one downstream of the first)

em++ orders its own search correctly -- libc++, then the sysroot, then builtins LAST --
so the injection is the whole problem, and removing it restores the order libc++ needs.

Five command-line approaches failed to outrank it, each a full CI round:

    -resource-dir=<em++'s>     no effect; separate from the injected path
    -nobuiltininc              removes clang's OWN builtins (the last entry), not this one
    libclang 17 / 19 / 20      identical 126 errors; the version was never the issue
    --include-paths=<libc++>   first on the command line, searched EIGHTH -- clang drops a
                               normal include dir that duplicates a system dir and keeps
                               the system position
    -isystem<libc++>           still lands after: shiboken assembles its own arguments
                               before the --clang-option ones are appended

The last of those is the general lesson: nothing passed through --clang-option can
precede what shiboken adds itself, so an option was never going to fix this.

Idempotent, and reversible by simply not setting the variable.
"""
import io
import os
import sys

REL = 'sources/shiboken6/ApiExtractor/clangparser/compilersupport.cpp'
SIG = 'static void appendClangBuiltinIncludes(HeaderPaths *p)'
MARK = 'FCWEB: return unconditionally'

GUARD = '''{
    // FCWEB: return unconditionally. shiboken places this directory ahead of everything
    // the compiler reports, so its <stddef.h> beats libc++'s and every header after
    // <cstddef> fails to parse. em++ already orders its own search correctly -- libc++,
    // sysroot, builtins LAST -- which is exactly what libc++ requires.
    //
    // Unconditional, not env-gated: the generator is invoked through the generated
    // shiboken_wrapper.sh, which does not pass this environment through, so a run-time
    // check never fired. This pyside-setup tree is built solely for the wasm target, so
    // there is nothing else here to preserve the behaviour for.
    return;
'''


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    path = os.path.join(sys.argv[1], REL)
    if not os.path.exists(path):
        sys.exit('not found: %s' % path)

    src = io.open(path, encoding='utf-8', errors='replace').read()

    if MARK in src:
        print('  already patched: %s' % REL)
        return

    # A cached tree may carry the earlier ENV-GATED form, which never fired because the
    # generator runs through a wrapper that drops the environment. Upgrade it in place
    # rather than adding a second guard.
    old_form = ('if (!qEnvironmentVariableIsEmpty("FCWEB_SHIBOKEN_NO_BUILTIN_INCLUDES"))'
                + chr(10) + '        return;')
    if old_form in src:
        src = src.replace(old_form, 'return;   // FCWEB: return unconditionally', 1)
        io.open(path, 'w', encoding='utf-8', newline='').write(src)
        print('  %s: env-gated guard upgraded to unconditional' % REL)
        return

    if SIG not in src:
        print('!! signature not found in %s' % REL)
        print('   expected: %s' % SIG)
        print('   lines mentioning appendClangBuiltinIncludes:')
        for i, line in enumerate(src.split(chr(10)), 1):
            if 'appendClangBuiltinIncludes' in line:
                print('     %d: %s' % (i, line.strip()))
        sys.exit(1)

    # The body opens with a "{" on the line after the signature.
    i = src.index(SIG) + len(SIG)
    j = src.index('{', i)
    src = src[:j] + GUARD + src[j + 1:]

    io.open(path, 'w', encoding='utf-8', newline='').write(src)
    print('  %s: appendClangBuiltinIncludes() can now be skipped' % REL)


if __name__ == '__main__':
    main()
