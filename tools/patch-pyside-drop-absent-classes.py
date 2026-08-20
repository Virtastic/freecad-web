"""Stop PySide expecting QProcess::UnixProcessParameters, which Qt-for-wasm has not got.

    python tools/patch-pyside-drop-absent-classes.py deps/src/pyside-setup

Without this the QtCore module stops at AUTOMOC, long after the generator has run:

    AutoGen error
    Info error in info file ".../QtCore_autogen.dir/AutogenInfo.json":
    The source file "BIN:/PySide6/QtCore/PySide6/QtCore/qprocess_unixprocessparameters_wrapper.cpp"
    does not exist.

WHY

PySide picks the platform-specific wrapper in PySide6/QtCore/CMakeLists.txt:

    if(ENABLE_WIN)
        set(SPECIFIC_OS_FILES ${QtCore_GEN_DIR}/qwineventnotifier_wrapper.cpp)
    else()
        set(SPECIFIC_OS_FILES ${QtCore_GEN_DIR}/qprocess_unixprocessparameters_wrapper.cpp)
    endif()

and ENABLE_WIN comes from check_os() in cmake/PySideHelpers.cmake, which reads
CMAKE_HOST_APPLE / CMAKE_HOST_WIN32 -- the HOST, not the target. Cross-compiling from
Linux to wasm therefore takes the Unix branch and asks for a class the target does not
have. The generator is right and cmake is wrong.

The whole of QProcess is absent from Qt for WebAssembly -- there are no subprocesses in a
browser, which is why toolchain/include/qprocess_stub.h exists and why patches/freecad.patch
#ifs out every connect() to a QProcess signal. shiboken says so plainly:

    typesystem_core_common.xml:2650: type 'QProcess' ...        (and 2652-2660, its enums)
    typesystem_core_common.xml:2661: type 'UnixProcessParameters' ...

Only this ONE wrapper goes missing, though, because QProcess and QProcessEnvironment carry

    <configuration condition="QT_CONFIG(process)"/>

so shiboken still writes their files with the body #if'd out, and cmake finds them. The
nested <value-type name="UnixProcessParameters"> has no such condition, so nothing is
written at all. Hence a one-file fix, not a QProcess-wide one.

The replacement follows the idiom already in that file for "permissions" and
"sharedmemory": drop the type entry, drop the source. EMSCRIPTEN is checked as well as the
Qt feature so the guard does not hinge on "process" appearing in QT_DISABLED_PUBLIC_FEATURES.

The dropped entry is spelled with a DOT. shiboken's shouldDropTypeEntry() qualifies nested
names by prepending the enclosing entry and a '.', so "QProcess::UnixProcessParameters"
would silently match nothing.

Idempotent -- safe to re-run over a cached source tree.
"""
import io
import os
import sys

REL = 'sources/pyside6/PySide6/QtCore/CMakeLists.txt'
MARK = 'FCWEB: QProcess::UnixProcessParameters'
ANCHOR = 'if("permissions" IN_LIST QtCore_disabled_features)'

BLOCK = '''# FCWEB: QProcess::UnixProcessParameters is not in Qt for WebAssembly -- a browser has
# no subprocesses, and shiboken reports the whole of QProcess missing. QProcess and
# QProcessEnvironment survive it because their typesystem entries carry
# <configuration condition="QT_CONFIG(process)"/>, so a guarded (empty) wrapper is still
# written; this nested value-type has no such condition, so no file appears and AUTOMOC
# stops with "The source file ...qprocess_unixprocessparameters_wrapper.cpp does not exist".
#
# It is asked for at all only because check_os() in cmake/PySideHelpers.cmake decides
# ENABLE_WIN from CMAKE_HOST_WIN32 -- the host, not the target -- so a Linux-to-wasm cross
# build takes the Unix branch.
#
# Same shape as the "permissions" and "sharedmemory" cases below. The entry is spelled with
# a DOT because shiboken qualifies nested names with '.', not '::'.
if(EMSCRIPTEN OR "process" IN_LIST QtCore_disabled_features)
    list(APPEND QtCore_DROPPED_ENTRIES QProcess.UnixProcessParameters)
    list(REMOVE_ITEM QtCore_SRC ${QtCore_GEN_DIR}/qprocess_unixprocessparameters_wrapper.cpp)
    message(STATUS "Qt${QT_MAJOR_VERSION}Core: Dropping QProcess::UnixProcessParameters (absent on this target)")
endif()

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

    if ANCHOR not in src:
        print('!! anchor not found in %s' % REL)
        print('   expected: %s' % ANCHOR)
        print('   lines mentioning QtCore_disabled_features:')
        for i, line in enumerate(src.split(chr(10)), 1):
            if 'QtCore_disabled_features' in line or 'SPECIFIC_OS_FILES' in line:
                print('     %d: %s' % (i, line.strip()))
        sys.exit(1)

    # Must land AFTER get_property(QtCore_disabled_features ...) and after QtCore_SRC is
    # set; the anchor is the first use of the feature list, which satisfies both.
    src = src.replace(ANCHOR, BLOCK + ANCHOR, 1)
    io.open(path, 'w', encoding='utf-8', newline='').write(src)
    print('  %s: QProcess::UnixProcessParameters dropped on wasm' % REL)


if __name__ == '__main__':
    main()
