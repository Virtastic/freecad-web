"""Add clang options to shiboken's emscripten branch, each independently switchable.

    python tools/patch-pyside-clang-options.py deps/src/pyside-setup

    FCWEB_SHIBOKEN_VERBOSE=1        add -v            (print the include search list)
    FCWEB_SHIBOKEN_RESOURCE_DIR=1   add -resource-dir=<em++'s>
    FCWEB_SHIBOKEN_NOBUILTININC=1   add -nobuiltininc
    FCWEB_SHIBOKEN_STD=c++17        add -std=c++17

With none set it adds nothing, and re-running always normalises the file back to the
requested set -- so a cached source tree cannot carry a stale combination.

WHY THIS EXISTS, and the history, because the symptom is misleading:

    <cstddef> tried including <stddef.h> but didn't find libc++'s <stddef.h> header.
    ... you are probably using compiler flags that make that not be the case
    error: unknown type name 'nullptr_t'        (x125 more, all downstream of the first)

libc++'s <cstddef> requires <stddef.h> to resolve to libc++'s OWN copy. If any C library
or compiler-builtin stddef.h precedes c++/v1 in the search list, it stops there and every
later header falls apart. The message is about ORDER, not a missing file -- which took
several rounds to accept, because the count (126) never moved regardless of libclang
version (17/19/20), resource directory, or -std, and an invariant number reads like the
knob being irrelevant rather than the knob being the wrong knob.

`-v` settled it in one run. The search list was:

    deps/host/llvm-<v>/lib/clang/<v>/include   <- INJECTED, ahead of libc++
    .../sysroot/include/c++/v1
    .../sysroot/include
    emsdk/upstream/lib/clang/<v>/include       <- em++'s own, correctly last

That first entry comes from CLANG_INSTALL_DIR, which rebuild-pyside-weh.sh used to export
-- added earlier to stop the generator picking a DIFFERENT llvm's builtins at run time
("No C++ classes found!"), a real problem when libclang was 17 and the distro had 21. So
one fix created the next, and the second one resisted three attempts from the wrong end.

Hence: keep each option separately switchable, and keep -v switchable independently of the
options it diagnoses. Gating the diagnostic behind one of the fixes means turning that fix
off also blinds you, which is exactly what happened.
"""
import io
import os
import sys

REL = 'sources/pyside6/cmake/Macros/PySideModules.cmake'
ANCHOR = 'list(APPEND shiboken_command "--clang-option=--target=wasm32-unknown-emscripten")'
BEGIN = '        # FCWEB-CLANG-OPTIONS-BEGIN'
END = '        # FCWEB-CLANG-OPTIONS-END'


LIBCXX_BEGIN = '    # FCWEB-LIBCXX-FIRST-BEGIN'
LIBCXX_END = '    # FCWEB-LIBCXX-FIRST-END'

# shiboken ALWAYS injects a clang builtins directory ahead of the compiler-discovered
# paths -- CLANG_INSTALL_DIR only chooses WHICH one (ours, or the distro's llvm-21 when
# unset). Its own --include-paths entries, however, come first of all. So the way to get
# libc++ ahead of a C stddef.h is to put it in that list.
LIBCXX_BLOCK = """
    # FCWEB-LIBCXX-FIRST-BEGIN
    # libc++ MUST precede any clang builtins directory: its <cstddef> does
    #   #include <stddef.h>
    # and requires that to resolve to libc++'s own copy. shiboken injects a builtins path
    # ahead of the compiler-discovered ones, so without this the C stddef.h wins and every
    # header after it fails with 'unknown type name nullptr_t'.
    if(EMSCRIPTEN)
        # em++ -print-sysroot prints nothing (verified: the warning below fired), so take
        # the sysroot from what the toolchain file actually sets, then fall back to
        # deriving it from the compiler's own location.
        set(_fcweb_sysroot "")
        foreach(_cand "${CMAKE_SYSROOT}" "${EMSCRIPTEN_SYSROOT}" "$ENV{EMSDK}/upstream/emscripten/cache/sysroot")
            if(_fcweb_sysroot STREQUAL "" AND EXISTS "${_cand}/include/c++/v1")
                set(_fcweb_sysroot "${_cand}")
            endif()
        endforeach()
        if(_fcweb_sysroot STREQUAL "")
            get_filename_component(_fcweb_emdir "${CMAKE_CXX_COMPILER}" DIRECTORY)
            if(EXISTS "${_fcweb_emdir}/cache/sysroot/include/c++/v1")
                set(_fcweb_sysroot "${_fcweb_emdir}/cache/sysroot")
            endif()
        endif()
        if(NOT _fcweb_sysroot STREQUAL "")
            message(STATUS "shiboken: libc++ first -> ${_fcweb_sysroot}/include/c++/v1")
            list(INSERT @LISTVAR@ 0 "${_fcweb_sysroot}/include/c++/v1")
        else()
            message(WARNING "shiboken: no include/c++/v1 found via CMAKE_SYSROOT, "
                            "EMSCRIPTEN_SYSROOT, EMSDK or the compiler path -- libc++ will "
                            "not precede the injected clang builtins and every header after "
                            "<cstddef> will fail")
        endif()
    endif()
    # FCWEB-LIBCXX-FIRST-END
"""


def strip_named(src, begin, end):
    """Remove a sentinel-delimited block. Sentinels, not pattern matching: an earlier
    line-based strip cut a block mid-statement and left a truncated execute_process("""
    keep, drop = [], False
    for line in src.split(chr(10)):
        if line.strip() == begin.strip():
            drop = True
            continue
        if line.strip() == end.strip():
            drop = False
            continue
        if not drop:
            keep.append(line)
    return chr(10).join(keep)


def build_block():
    lines = [BEGIN,
             '        # Generated by tools/patch-pyside-clang-options.py -- do not edit.']
    if os.environ.get('FCWEB_SHIBOKEN_RESOURCE_DIR') == '1':
        lines += [
            '        execute_process(COMMAND ${CMAKE_CXX_COMPILER} -print-resource-dir',
            '                        OUTPUT_VARIABLE _fcweb_em_resource',
            '                        OUTPUT_STRIP_TRAILING_WHITESPACE ERROR_QUIET)',
            '        if(_fcweb_em_resource)',
            '            list(APPEND shiboken_command',
            '                 "--clang-option=-resource-dir=${_fcweb_em_resource}")',
            '        endif()',
        ]
    if os.environ.get('FCWEB_SHIBOKEN_NOBUILTININC') == '1':
        lines.append('        list(APPEND shiboken_command "--clang-option=-nobuiltininc")')
    std = os.environ.get('FCWEB_SHIBOKEN_STD')
    if std:
        lines.append('        list(APPEND shiboken_command "--clang-option=-std=%s")' % std)
    if os.environ.get('FCWEB_SHIBOKEN_VERBOSE') == '1':
        # independent of everything above: the point is to SEE what the others did
        lines.append('        list(APPEND shiboken_command "--clang-option=-v")')
    lines.append(END)
    return '\n' + '\n'.join(lines)


def strip_block(src):
    keep, drop = [], False
    for line in src.split('\n'):
        if line.strip() == BEGIN.strip():
            drop = True
            continue
        if line.strip() == END.strip():
            drop = False
            continue
        if not drop:
            keep.append(line)
    return '\n'.join(keep)


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    path = os.path.join(sys.argv[1], REL)
    if not os.path.exists(path):
        sys.exit('not found: %s' % path)

    src = io.open(path, encoding='utf-8', errors='replace').read()

    # Always normalise first: a cached tree may carry a block from a previous combination,
    # or from the older patch-pyside-resource-dir.py.
    src = strip_block(src)
    for old_begin, old_end in [('# FCWEB-RESOURCE-DIR-BEGIN', '# FCWEB-RESOURCE-DIR-END')]:
        if old_begin in src:
            keep, drop = [], False
            for line in src.split('\n'):
                if old_begin in line:
                    drop = True
                    continue
                if old_end in line:
                    drop = False
                    continue
                if not drop:
                    keep.append(line)
            src = '\n'.join(keep)
            print('  removed a block from the previous tool')

    # Strip the libc++ block here too, BEFORE any early return -- otherwise asking for
    # nothing leaves a previous run's block in place and the "normalised" file is not.
    src = strip_named(src, LIBCXX_BEGIN, LIBCXX_END)

    block = build_block()
    opts = [l.split('--clang-option=')[1].rstrip('")') for l in block.split('\n')
            if '--clang-option=' in l]
    want_libcxx = os.environ.get('FCWEB_SHIBOKEN_LIBCXX_FIRST') == '1'
    if not opts and 'execute_process' not in block and not want_libcxx:
        io.open(path, 'w', encoding='utf-8', newline='').write(src)
        print('  %s: no extra clang options requested' % REL)
        return

    if ANCHOR not in src:
        print('!! anchor not found in %s' % REL)
        print('   Expected the emscripten branch from patches/pyside-setup.patch:')
        print('     %s' % ANCHOR)
        sys.exit(1)

    # Put libc++ at the FRONT of shiboken's own --include-paths. Those entries precede the
    # clang builtins directory shiboken injects, and that injected directory is what makes
    # a C stddef.h win over libc++'s. Requested with FCWEB_SHIBOKEN_LIBCXX_FIRST=1.
    if want_libcxx:
        hits = [l for l in src.split(chr(10)) if 'make_path(shiboken_include_dirs' in l]
        if not hits:
            print('!! cannot find make_path(shiboken_include_dirs ...) in %s' % REL)
            print('   The include-path list is built differently than expected; lines seen:')
            for i, line in enumerate(src.split(chr(10)), 1):
                if 'include_dir' in line or 'include-paths' in line:
                    print('     %d: %s' % (i, line.strip()))
            sys.exit(1)
        target = hits[0]
        listvar = target.split('make_path(shiboken_include_dirs')[1].strip().rstrip(')').strip()
        if not listvar.startswith('${'):
            print('!! unexpected make_path form: %s' % target.strip())
            sys.exit(1)
        listvar = listvar[2:].rstrip('}')
        # lstrip the leading newline: the strip removes only the sentinel lines, so a
        # leading blank would accumulate and the round trip would not be exact.
        src = src.replace(
            target,
            LIBCXX_BLOCK.replace('@LISTVAR@', listvar).lstrip(chr(10)) + target, 1)
        print('  %s: libc++ inserted at the front of %s' % (REL, listvar))

    src = src.replace(ANCHOR, ANCHOR + block, 1)
    io.open(path, 'w', encoding='utf-8', newline='').write(src)
    print('  %s: clang options -> %s' % (REL, ' '.join(opts) if opts else '(resource-dir)'))


if __name__ == '__main__':
    main()
