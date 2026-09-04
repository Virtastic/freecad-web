# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) Virtastic
"""Stop PySide expecting wrappers for classes Qt-for-wasm has not got.

    python tools/patch-pyside-drop-absent-classes.py deps/src/pyside-setup

Without this the QtCore module stops at AUTOMOC, long after the generator has run:

    AutoGen error
    Info error in info file ".../QtCore_autogen.dir/AutogenInfo.json":
    The source file "BIN:/PySide6/QtCore/PySide6/QtCore/qprocess_wrapper.cpp" does not exist.

WHY

PySide6/QtCore/CMakeLists.txt lists every wrapper .cpp the generator is expected to write.
shiboken writes one per class it FINDS, so a class absent from the target's headers leaves a
listed-but-missing file. It says so plainly first -- these are its own words from the run
that produced this list:

    type 'QProcess' is specified in typesystem, but not defined (disabled by configuration?)
    type 'QSystemSemaphore' ...
    type 'QTimeZone::OffsetData' ...

and a `<configuration condition="QT_CONFIG(...)"/>` on the entry does NOT save it: that
guards the generated body, and nothing is generated at all when the class is missing.
(An earlier version of this file assumed otherwise and fixed only one of the three.)

Upstream already does exactly this for two other classes in the same file -- "permissions"
and "sharedmemory" -- so the shape below is the file's own idiom, applied to the cases it
does not cover. QSystemSemaphore is the conspicuous one: it is the sibling of QSharedMemory
and is missing the same treatment.

QProcess::UnixProcessParameters is asked for at all only because check_os() in
cmake/PySideHelpers.cmake decides ENABLE_WIN from CMAKE_HOST_WIN32 -- the HOST, not the
target -- so a Linux-to-wasm cross build takes the Unix branch.

WHAT IS NOT DROPPED

  QProcessEnvironment      found: "processenvironment" is a separate Qt feature and is
                           still enabled, which is also why App/Application.cpp compiles.
  QTimeZone                found; only its QT_CONFIG(timezone) OffsetData struct is absent.
  QNativeInterface::QX11Application, QNativeInterface::QWindowsScreen
                           warned about, but QtGui/CMakeLists.txt already gates them on the
                           "xcb" feature and WIN32, so no file is expected either way.

Dropped entries are spelled with a DOT for nesting. shiboken's shouldDropTypeEntry()
qualifies nested names by prepending the enclosing entry and a '.', so
"QProcess::UnixProcessParameters" would silently match nothing.

Idempotent -- safe to re-run over a cached source tree.
"""
import io
import os
import sys

MARK = 'FCWEB-DROP-ABSENT'

# Per module: where its CMakeLists is, and the line to insert before. The anchor
# has to sit after both get_property(<mod>_disabled_features ...) and
# set(<mod>_SRC ...), because the block below appends to one and removes from the
# other.
MODULES = {
    'QtCore': {
        'rel': 'sources/pyside6/PySide6/QtCore/CMakeLists.txt',
        'anchor': 'if("permissions" IN_LIST QtCore_disabled_features)',
    },
    'QtNetwork': {
        'rel': 'sources/pyside6/PySide6/QtNetwork/CMakeLists.txt',
        'anchor': 'set(QtNetwork_SRC',
        'anchor_after': True,   # this list IS the thing being edited
    },
}

# (Qt feature, [type entries], [wrapper sources], why)
#
# Measured, not guessed: every entry here was reported absent by shiboken against the
# 6.11.2 Qt-for-wasm build. EMSCRIPTEN is checked alongside the feature so the guard does
# not hinge on the feature name appearing in QT_DISABLED_PUBLIC_FEATURES.
DROPS = {'QtCore': [
    ('process',
     ['QProcess', 'QProcess.UnixProcessParameters'],
     ['qprocess_wrapper.cpp', 'qprocess_unixprocessparameters_wrapper.cpp'],
     'a browser has no subprocesses. Same absence as toolchain/include/qprocess_stub.h,\n'
     '# which exists to keep FreeCAD itself compiling against the missing class.'),
    ('systemsemaphore',
     ['QSystemSemaphore'],
     ['qsystemsemaphore_wrapper.cpp'],
     'no SysV/POSIX semaphores under emscripten. Upstream gates its sibling QSharedMemory\n'
     '# on "sharedmemory" a few lines below and simply does not cover this one.'),
    ('timezone',
     ['QTimeZone.OffsetData'],
     ['qtimezone_offsetdata_wrapper.cpp'],
     'QTimeZone itself IS found and keeps its wrapper; only the nested OffsetData struct,\n'
     '# which sits inside QT_CONFIG(timezone), is absent.'),
], 'QtNetwork': [
    # Measured the same way as the QtCore entries above: these are the exact three
    # types shiboken reported as "specified in typesystem, but not defined" when
    # QtNetwork was first built for wasm. Nothing here is guessed, and the list is
    # short because Qt-for-wasm's QtNetwork is otherwise complete.
    ('networkinterface',
     ['QNetworkInterface', 'QNetworkAddressEntry'],
     ['qnetworkinterface_wrapper.cpp', 'qnetworkaddressentry_wrapper.cpp'],
     'a page cannot enumerate network interfaces, so Qt-for-wasm builds without\n'
     '# QT_FEATURE_networkinterface and neither class exists. QNetworkAddressEntry\n'
     '# is declared inside qnetworkinterface.h, which is why both go together.'),
    ('ssl',
     ['QSslEllipticCurve'],
     ['qsslellipticcurve_wrapper.cpp'],
     'the wasm TLS backend is certificate-only (QTlsBackendCertOnlyPlugin), so the\n'
     '# elliptic-curve type is absent while the rest of the QSsl* family is present.'),
]}


def block(mod, feature, entries, sources, why):
    lines = ['# %s: %s' % (MARK, why)]
    lines.append('if(EMSCRIPTEN OR "%s" IN_LIST %s_disabled_features)' % (feature, mod))
    lines.append('    list(APPEND %s_DROPPED_ENTRIES %s)' % (mod, ' '.join(entries)))
    lines.append('    list(REMOVE_ITEM %s_SRC' % mod)
    for s in sources:
        lines.append('         ${%s_GEN_DIR}/%s' % (mod, s))
    lines.append('    )')
    lines.append('    message(STATUS "%s: Dropping %s (absent on this target)")'
                 % (mod, ', '.join(entries)))
    lines.append('endif()')
    lines.append('')
    return chr(10).join(lines)


def patch_module(root, mod):
    """Returns True if the file was changed, False if it was already patched."""
    spec = MODULES[mod]
    rel = spec['rel']
    anchor = spec['anchor']
    path = os.path.join(root, rel)
    if not os.path.exists(path):
        # A module the build does not include is not an error: MODULES is the union of
        # everything this port has ever needed, and QtNetwork only appeared when the
        # Addon Manager did.
        print('  %s: not in this source tree, skipping' % rel)
        return False

    src = io.open(path, encoding='utf-8', errors='replace').read()
    if MARK in src:
        print('  already patched: %s' % rel)
        return False

    # A cached tree may carry the earlier version of this patch, which covered
    # QProcess's nested value-type only. Start from the pristine file rather than
    # stacking a second block on top of it.
    old_mark = 'FCWEB: QProcess::UnixProcessParameters'
    if old_mark in src:
        keep, dropping = [], False
        for line in src.split(chr(10)):
            if old_mark in line:
                dropping = True
            if dropping:
                if line.strip() == 'endif()':
                    dropping = False
                continue
            keep.append(line)
        src = chr(10).join(keep)
        print('  %s: superseded the earlier UnixProcessParameters-only block' % rel)

    if anchor not in src:
        print('!! anchor not found in %s' % rel)
        print('   expected: %s' % anchor)
        for i, line in enumerate(src.split(chr(10)), 1):
            if (mod + '_disabled_features') in line or (mod + '_SRC') in line:
                print('     %d: %s' % (i, line.strip()))
        sys.exit(1)

    text = ''.join(block(mod, *d) for d in DROPS[mod])
    if spec.get('anchor_after'):
        # The anchor IS the list being edited, so the block has to follow the whole
        # set(...) call rather than precede it -- REMOVE_ITEM on a variable that does
        # not exist yet silently does nothing, which would look exactly like success.
        i = src.index(anchor)
        j = src.index(')', src.index('_wrapper.cpp', i))
        j = src.index(chr(10), j) + 1
        src = src[:j] + text + src[j:]
    else:
        src = src.replace(anchor, text + anchor, 1)
    io.open(path, 'w', encoding='utf-8', newline='').write(src)
    print('  %s: dropped %d absent class group(s)' % (rel, len(DROPS[mod])))
    return True


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    root = sys.argv[1]
    changed = 0
    for mod in MODULES:
        changed += 1 if patch_module(root, mod) else 0
    print('  %d module(s) patched' % changed)

if __name__ == '__main__':
    main()
