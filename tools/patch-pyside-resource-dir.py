"""Give shiboken's parser emscripten's clang resource headers.

    python tools/patch-pyside-resource-dir.py deps/src/pyside-setup

patches/pyside-setup.patch already points shiboken at em++ for the wasm build, and says
why: the host libc++ uses builtins a older libclang cannot parse, so the Emscripten target
sysroot's libc++ is used instead. That gets the SYSTEM headers right.

It does not get the FREESTANDING ones right. libclang resolves <stddef.h>, <stdarg.h> and
friends from its OWN resource directory -- the one belonging to whichever libclang the
generator was linked against, here LLVM 17.0.6 -- while the libc++ being parsed is
emscripten's. emscripten's libc++ notices and refuses:

    error: <cstddef> tried including <stddef.h> but didn't find libc++'s <stddef.h> header.
           This usually means that your header search paths ...
    error: no member named 'nullptr_t' in the global namespace

after which nothing parses, every wrapper comes out empty, and the build fails hundreds of
files later with no mention of clang.

Note the symmetric failure: pointing the parser at a DIFFERENT LLVM's builtins (the
distro's llvm-21, while linked against 17) produces

    qt.shiboken: No C++ classes found!

So both "wrong resource dir" and "no resource dir" fail, in ways that name neither. The fix
is to hand the parser the resource directory belonging to the compiler whose sysroot it is
being asked to read -- em++'s own, via -print-resource-dir.

Idempotent -- safe to re-run.
"""
import io
import os
import re
import sys

REL = 'sources/pyside6/cmake/Macros/PySideModules.cmake'

ANCHOR = 'list(APPEND shiboken_command "--clang-option=--target=wasm32-unknown-emscripten")'

BEGIN = '        # FCWEB-RESOURCE-DIR-BEGIN'
END = '        # FCWEB-RESOURCE-DIR-END'

ADDITION = '''
        # FCWEB-RESOURCE-DIR-BEGIN
        # libclang resolves the FREESTANDING headers (stddef.h, stdarg.h) from its own
        # resource directory, which belongs to whatever libclang the generator was linked
        # against -- not to em++, whose libc++ is being parsed. emscripten's libc++ detects
        # the mismatch and stops with
        #   <cstddef> tried including <stddef.h> but didn't find libc++'s <stddef.h>
        # and then no class in any header parses. Hand it em++'s own resource headers.
        execute_process(COMMAND ${CMAKE_CXX_COMPILER} -print-resource-dir
                        OUTPUT_VARIABLE _fcweb_em_resource
                        OUTPUT_STRIP_TRAILING_WHITESPACE
                        ERROR_QUIET)
        if(_fcweb_em_resource AND EXISTS "${_fcweb_em_resource}/include")
            message(STATUS "shiboken: emscripten clang resource dir ${_fcweb_em_resource}")
            # -resource-dir ONLY. An -isystem<resource>/include alongside it puts the
            # builtin headers ahead of libc++'s own directory, and libc++'s <cstddef> uses
            # #include_next -- so the very header it is looking for stops being "next":
            #   <cstddef> tried including <stddef.h> but didn't find libc++'s <stddef.h>
            # The message says libc++'s stddef.h, not the compiler's, which is the clue:
            # this is include ORDER, not a missing file or a version mismatch.
            list(APPEND shiboken_command
                 "--clang-option=-resource-dir=${_fcweb_em_resource}")
        else()
            message(WARNING "shiboken: em++ -print-resource-dir gave nothing; the parser "
                            "will use libclang's own builtins and emscripten's libc++ will "
                            "refuse to include <stddef.h>")
        endif()
        # FCWEB-RESOURCE-DIR-END'''


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    path = os.path.join(sys.argv[1], REL)
    if not os.path.exists(path):
        sys.exit('not found: %s' % path)

    src = io.open(path, encoding='utf-8', errors='replace').read()

    # Keyed on the CURRENT form. An earlier version of this tool also injected an
    # -isystem, which broke libc++'s #include_next chain; a tree patched by that
    # version must be re-patched, not skipped.
    if '_fcweb_em_resource' in src and os.environ.get('FCWEB_SHIBOKEN_RESOURCE_DIR') != '1':
        print('  %s: removing the resource-dir override (not needed with a matching libclang)' % REL)
        keep, drop = [], False
        for line in src.split(chr(10)):
            if line.strip() == BEGIN.strip():
                drop = True
                continue
            if line.strip() == END.strip():
                drop = False
                continue
            if not drop:
                keep.append(line)
        io.open(path, 'w', encoding='utf-8', newline='').write(chr(10).join(keep))
        return
    if '-resource-dir=${_fcweb_em_resource}' in src:
        print('  already patched: %s' % REL)
        return
    if '-isystem${_fcweb_em_resource}' in src:
        print('  re-patching %s: dropping the -isystem that broke #include_next' % REL)
        out, skip_next = [], False
        for line in src.split('\n'):
            if '-isystem${_fcweb_em_resource}' in line:
                # the option sits on its own line, preceded by a bare list(APPEND ...)
                while out and out[-1].strip() == 'list(APPEND shiboken_command':
                    out.pop()
                continue
            out.append(line)
        io.open(path, 'w', encoding='utf-8', newline='').write('\n'.join(out))
        return

    if ANCHOR not in src:
        print('!! anchor not found in %s' % REL)
        print('   Expected the emscripten branch added by patches/pyside-setup.patch:')
        print('     %s' % ANCHOR)
        print('   Present --clang-option lines:')
        for i, line in enumerate(src.split('\n'), 1):
            if 'clang-option' in line or 'compiler-path' in line:
                print('     %d: %s' % (i, line.strip()))
        sys.exit(1)

    if os.environ.get('FCWEB_SHIBOKEN_RESOURCE_DIR') != '1':
        # Default: add nothing. With libclang matching emsdk's clang (both 20) the
        # parser's own resource directory is already the right one, and overriding it
        # was only ever a workaround for a mismatched libclang. Set
        # FCWEB_SHIBOKEN_RESOURCE_DIR=1 to re-enable the override.
        print('  %s: no resource-dir override needed (libclang matches emsdk clang)' % REL)
        return
    src = src.replace(ANCHOR, ANCHOR + ADDITION, 1)
    io.open(path, 'w', encoding='utf-8', newline='').write(src)
    print('  added em++ resource-dir options to %s' % REL)


if __name__ == '__main__':
    main()
