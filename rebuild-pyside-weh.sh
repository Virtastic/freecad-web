#!/bin/bash
# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) Virtastic
set -e
cd "$(dirname "$0")"
. toolchain/env.sh

# emsdk ships whichever node its installer chose -- 22.16.0 here, 24.19.0 on a hosted
# runner -- so a hardcoded path is a build that only works on one machine. emsdk_env.sh
# exports EMSDK_NODE; fall back to PATH, and fail by name rather than handing cmake a
# CMAKE_CROSSCOMPILING_EMULATOR that does not exist.
FCWEB_NODE="${EMSDK_NODE:-$(command -v node)}"
[ -x "$FCWEB_NODE" ] || { echo "ERROR: no node found (EMSDK_NODE unset and none on PATH)" >&2; exit 1; }
QNEW="$ROOT/qt/6.9.0/wasm_mt_weh"
TC="$ROOT/emsdk/upstream/emscripten/cmake/Modules/Platform/Emscripten.cmake"
NODE="$FCWEB_NODE"
CPY="$ROOT/deps/src/cpython"

# Everything below used to be written for one machine: a macOS host Qt, a macOS-only
# python.exe, and /usr/bin/python3. Resolve each instead, and fail naming what is missing
# rather than handing cmake a path that does not exist.

# Host Qt: the wasm build needs the host tools (moc, rcc, qmake). build-qt-wasm.yml
# installs them to qt-host/6.9.0/gcc_64 on Linux; the build machine has qt/6.9.0/macos.
QT_HOST=""
for d in "$ROOT/qt-host/6.9.0/gcc_64" "$ROOT/qt/6.9.0/macos" "$ROOT/qt/6.9.0/gcc_64" \
         "$ROOT/qt-host/6.9.0/macos"; do
    if [ -x "$d/bin/qmake" ] || [ -x "$d/bin/moc" ]; then QT_HOST="$d"; break; fi
done
[ -n "$QT_HOST" ] || { echo "ERROR: no host Qt found (looked for bin/qmake under qt-host/6.9.0/gcc_64, qt/6.9.0/macos, ...)" >&2; exit 1; }
echo "host Qt:      $QT_HOST"

# Host interpreter that RUNS during the build (shiboken's generator, cmake probes). Not
# the wasm CPython.
HOSTPY3="$(command -v python3 || command -v python)"
[ -n "$HOSTPY3" ] || { echo "ERROR: no python3 on PATH" >&2; exit 1; }
echo "host python:  $HOSTPY3"

# CPython's own host build: python.exe on macOS, python or python3-native elsewhere.
WASMPY_HOST=""
for c in "$CPY/builddir/build/python.exe" "$CPY/builddir/build/python" \
         "$CPY/builddir/build/python3-native"; do
    [ -x "$c" ] && { WASMPY_HOST="$c"; break; }
done
[ -n "$WASMPY_HOST" ] || { echo "ERROR: no CPython host build under $CPY/builddir/build" >&2; exit 1; }
echo "cpython host: $WASMPY_HOST"

# CMake's FindPython reads pyconfig.h out of Python_INCLUDE_DIR, and CPython does not ship
# it in Include/ -- configure generates it into the build tree:
#   file STRINGS ".../deps/src/cpython/Include/pyconfig.h" cannot be read
# It must be ONE directory holding both, so assemble one. Fourth script to need this
# (numpy, matplotlib, pivy, IfcOpenShell were the others); the wasm pyconfig.h, never the
# host's, or every target unit fails on LONG_BIT instead.
PYINC="$ROOT/build-pyinc-wasm"
if [ ! -f "$PYINC/Python.h" ] || [ ! -f "$PYINC/pyconfig.h" ]; then
    if [ -f "$CPY/builddir/emscripten-mt/pyconfig.h" ]; then
        rm -rf "$PYINC" && mkdir -p "$PYINC"
        cp -r "$CPY/Include/." "$PYINC/"
        cp "$CPY/builddir/emscripten-mt/pyconfig.h" "$PYINC/pyconfig.h"
    else
        echo "ERROR: no wasm pyconfig.h under $CPY/builddir/emscripten-mt" >&2
        exit 1
    fi
fi
echo "python inc:   $PYINC"

[ -d "$ROOT/deps/host/shiboken6" ] || {
    echo "ERROR: no host shiboken at $ROOT/deps/host/shiboken6." >&2
    echo "       The wasm shiboken needs the HOST generator, which is built against" >&2
    echo "       libclang. Build it first (see build-shiboken-host.sh)." >&2
    exit 1; }
# The generator resolves clang's builtin headers at RUN time, not link time. Without this
# it searches on its own, finds whichever LLVM the distro has, and mismatched builtins make
# every Qt header fail to parse -- reported as:
#   qt.shiboken: CLANG v0.64, builtins includes directory: /usr/lib/llvm-21/lib/clang/21/include
#   qt.shiboken: No C++ classes found!
# which looks like a typesystem fault and is not. build-shiboken-host.sh records the prefix
# it built against; use exactly that one.
if [ -f "$ROOT/deps/host/shiboken6/.llvm-prefix" ]; then
    LLVM_PREFIX="$(cat "$ROOT/deps/host/shiboken6/.llvm-prefix")"
    if [ -d "$LLVM_PREFIX" ]; then
        # DO NOT export CLANG_INSTALL_DIR here. shiboken turns it into an -I of
        # <prefix>/lib/clang/<ver>/include and places it BEFORE the compiler-discovered
        # paths. clang -v showed the result:
        #
        #   deps/host/llvm-20.1.8/lib/clang/20/include   <- injected, ahead of libc++
        #   .../sysroot/include/c++/v1
        #
        # libc++'s <cstddef> does #include <stddef.h> and REQUIRES it to resolve to
        # libc++'s own copy; with a C stddef.h ahead of it, it stops with "didn't find
        # libc++'s <stddef.h>" and nullptr_t is undefined everywhere after.
        #
        # It was exported to stop the generator finding a DIFFERENT llvm's builtins at
        # run time ("No C++ classes found"), which mattered when libclang was 17 and the
        # distro had 21. With a self-contained libclang matching emsdk's clang, the
        # generator finds its own, and em++ supplies the sysroot in the right order.
        export FCWEB_LLVM_PREFIX="$LLVM_PREFIX"   # recorded for diagnostics only
        echo "llvm prefix:  $LLVM_PREFIX (NOT exported to shiboken -- see comment)"
    else
        echo "!! recorded LLVM prefix $LLVM_PREFIX no longer exists -- rebuild the host" >&2
        echo "   generator, or the bindings will come out empty." >&2
    fi
else
    echo "!! no .llvm-prefix beside the host shiboken. It will search for clang builtins on" >&2
    echo "   its own; if it picks a different LLVM than it was linked against, every header" >&2
    echo "   fails to parse and the generator reports 'No C++ classes found'." >&2
fi

# The parser needs em++'s freestanding headers, not libclang's own. See the tool for the
# full account; without it every Qt header fails to parse and the wrappers come out empty.
python3 "$ROOT/tools/patch-pyside-clang-options.py" "$ROOT/deps/src/pyside-setup"

# Diagnostic: print where shiboken injects the clang builtins include, which no
# command-line option has been able to outrank. Costs nothing and settles the shape.
python3 "$ROOT/tools/show-shiboken-includes.py" "$ROOT/deps/src/pyside-setup" || true

# Let the wasm shiboken skip injecting clang's builtin include directory. Nothing
# passed through --clang-option can precede what shiboken adds itself, so this is the
# only place the include order can be corrected. See the tool for the five failed
# command-line approaches.
python3 "$ROOT/tools/patch-shiboken-builtin-includes.py" "$ROOT/deps/src/pyside-setup"
export FCWEB_SHIBOKEN_NO_BUILTIN_INCLUDES=1

# The binutils used below, resolved once: the skip decision needs nm too.
NM="$ROOT/emsdk/upstream/bin/llvm-nm"
if [ ! -x "$NM" ]; then
    echo "  llvm-nm not at $NM -- falling back to PATH"
    NM="$(command -v llvm-nm || command -v nm || true)"
fi
AR="$ROOT/emsdk/upstream/bin/llvm-ar"
[ -x "$AR" ] || AR="$(command -v llvm-ar || command -v ar || true)"

# Whether to BUILD. The verification and the pyside-pkg tree below always run, even on a
# restored cache -- a check that is skipped whenever the thing it checks was cached is a
# check that only ever runs when it cannot tell you anything. The workflow used to make this
# decision itself and skip the whole script, which had exactly that effect.
#
# The condition is the SYMBOL, not the file. A cached archive that emstrip had already
# emptied is exactly the artifact this lane must not accept, and keying the skip on the
# file's existence would have let that archive skip the very rebuild that fixes it.
SKIP_BUILD=""
QTW_A="$ROOT/build-pyside-wasm/PySide6/QtWidgets/QtWidgets.abi3.a"
if [ -s "$QTW_A" ] && [ -n "$NM" ] \
   && "$NM" "$QTW_A" 2>/dev/null | grep -q "PyInit_QtWidgets" \
   && [ "$FCWEB_PYSIDE_REBUILD" != "1" ]; then
    echo "=== PYSIDE: archives already present and carry their PyInit -- skipping the build"
    echo "    (set FCWEB_PYSIDE_REBUILD=1 to force a rebuild)"
    SKIP_BUILD=1
elif [ -s "$QTW_A" ]; then
    echo "=== PYSIDE: QtWidgets.abi3.a exists but has no PyInit_QtWidgets -- rebuilding"
fi

if [ -z "$SKIP_BUILD" ]; then
echo "=== SHIBOKEN (lib) ==="
rm -rf build-shiboken-wasm
cmake -S deps/src/pyside-setup/sources/shiboken6 -B build-shiboken-wasm -G Ninja \
  -DCMAKE_TOOLCHAIN_FILE="$TC" -DCMAKE_CROSSCOMPILING_EMULATOR="$NODE" \
  -DCMAKE_POLICY_VERSION_MINIMUM=3.5 -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_PROJECT_INCLUDE_BEFORE="$ROOT/force-static.cmake" \
  -DCMAKE_PREFIX_PATH="$QNEW;$ROOT/deps/host/shiboken6" \
  -DCMAKE_FIND_ROOT_PATH="$QNEW;$ROOT/deps/host/shiboken6" \
  -DCMAKE_FIND_ROOT_PATH_MODE_PACKAGE=BOTH \
  -DQt6_DIR="$QNEW/lib/cmake/Qt6" -DQT_HOST_PATH="$QT_HOST" \
  -DQFP_PYTHON_HOST_PATH="$HOSTPY3" -DQFP_SHIBOKEN_HOST_PATH="$ROOT/deps/host/shiboken6" \
  -DShiboken_SKIP_GENERATOR_BUILD=ON \
  -DPython_EXECUTABLE="$WASMPY_HOST" -DPython_INCLUDE_DIR="$PYINC" \
  -DPython_LIBRARY="$CPY/builddir/emscripten-mt/libpython3.13.a" -DPython_SOABI=cpython-313-wasm32-emscripten \
  `# See the QFP_NO_STRIP comment on the PySide configure below. Same reason here.` \
  -DQFP_NO_STRIP=ON -DCMAKE_STRIP=/usr/bin/true \
  -DCMAKE_INSTALL_PREFIX="$ROOT/deps/wasm/shiboken6" \
  -DCMAKE_CXX_FLAGS="-pthread -fwasm-exceptions"
ninja -C build-shiboken-wasm install

# QtCore lists wrappers for three classes Qt-for-wasm has not got -- QProcess (a browser has
# no subprocesses), QSystemSemaphore, and QTimeZone::OffsetData -- so the generator writes
# nothing for them and AUTOMOC stops. Must run before the PySide configure: the source list
# is fixed then, and the failure only surfaces at build time, after generation.
python3 "$ROOT/tools/patch-pyside-drop-absent-classes.py" "$ROOT/deps/src/pyside-setup"

echo "=== PYSIDE ==="
rm -rf build-pyside-wasm
cmake -S deps/src/pyside-setup/sources/pyside6 -B build-pyside-wasm -G Ninja \
  -DCMAKE_TOOLCHAIN_FILE="$TC" -DCMAKE_CROSSCOMPILING_EMULATOR="$NODE" \
  -DCMAKE_POLICY_VERSION_MINIMUM=3.5 -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_PROJECT_INCLUDE_BEFORE="$ROOT/force-static.cmake" \
  -DCMAKE_PREFIX_PATH="$QNEW;$ROOT/deps/wasm/shiboken6;$ROOT/deps/host/shiboken6" \
  -DCMAKE_FIND_ROOT_PATH="$QNEW;$ROOT/deps/wasm/shiboken6;$ROOT/deps/host/shiboken6" \
  -DCMAKE_FIND_ROOT_PATH_MODE_PACKAGE=BOTH \
  -DQt6_DIR="$QNEW/lib/cmake/Qt6" -DQT_HOST_PATH="$QT_HOST" \
  -DQFP_PYTHON_HOST_PATH="$HOSTPY3" -DQFP_SHIBOKEN_HOST_PATH="$ROOT/deps/host/shiboken6" \
  -DShiboken6_DIR="$ROOT/deps/wasm/shiboken6/lib/cmake/Shiboken6" \
  -DMODULES="Core;Gui;Widgets" -DFORCE_LIMITED_API=no \
  `# BUILD_TESTS=OFF: pysidetest parses HOST headers, and this build removes the clang` \
  `# builtins injection that host parsing genuinely needs, so it failed with` \
  `#   /usr/include/c++/15/cstddef: fatal error: 'stddef.h' file not found` \
  `# Same reason shiboken's own samplebinding is off. Only Core/Gui/Widgets are wanted.` \
  -DBUILD_TESTS=OFF \
  `# QFP_NO_OVERRIDE_OPTIMIZATION_FLAGS: append_size_optimization_flags() in` \
  `# cmake/Macros/PySideModules.cmake puts -ffunction-sections -fdata-sections` \
  `# -fno-exceptions on EVERY module target, after CMAKE_CXX_FLAGS -- so PySide's` \
  `# translation units would be built -fno-exceptions while the rest of this port` \
  `# (Qt, OCCT, FreeCAD) is built -fwasm-exceptions. Mixing exception models across` \
  `# one link is a defect this repository has already shipped once (OCCT, ROADMAP 12).` \
  -DQFP_NO_OVERRIDE_OPTIMIZATION_FLAGS=ON \
  -DPython_EXECUTABLE="$WASMPY_HOST" -DPython_INCLUDE_DIR="$PYINC" \
  -DPython_LIBRARY="$CPY/builddir/emscripten-mt/libpython3.13.a" -DPython_SOABI=cpython-313-wasm32-emscripten \
  `# QFP_NO_STRIP: create_pyside_module() ends with qfp_strip_library(), which adds a` \
  `# POST_BUILD "${CMAKE_STRIP} $<TARGET_FILE:...>" whenever` \
  `#     CMAKE_STRIP AND UNIX AND NOT APPLE AND NOT QFP_NO_STRIP AND NOT Debug` \
  `# (ShibokenHelpers.cmake:89). On this Linux runner CMAKE_STRIP is emstrip, which drops` \
  `# the symbol table outright: every archive member came back from llvm-nm as` \
  `#     QtCore.abi3.a:qabstractanimation_wrapper.cpp.o: no symbols` \
  `# and PyInit_QtCore -- which MainGui.cpp puts in the inittab -- was simply gone from a` \
  `# build that had otherwise linked 694/694 cleanly. The guard is NOT APPLE, so this` \
  `# never fired on the macOS build machine the port was written on. BUILD-WEH.md already` \
  `# warns "emstrip drops the symbol table"; nothing had applied it to this lane.` \
  -DQFP_NO_STRIP=ON -DCMAKE_STRIP=/usr/bin/true \
  -DCMAKE_INSTALL_PREFIX="$ROOT/emsdk/upstream/emscripten/cache/sysroot" \
  -DCMAKE_CXX_FLAGS="-pthread -fwasm-exceptions"
ninja -C build-pyside-wasm
fi   # SKIP_BUILD

# The link takes these four archives straight out of the build trees, so verify them HERE,
# by symbol -- ninja exiting 0 says the targets built, not that the Python modules came out
# usable. Each PyInit_ below is a PyImport_AppendInittab entry in MainGui.cpp, and a missing
# one is a trapping `import PySide6.QtWidgets` in the browser, not a link error, which is
# exactly the kind of failure this repository has already been bitten by four times.
# deps/wasm/pyside-pkg is the PRELOADED PYTHON TREE (--preload-file ...@/pyside-pkg in
# build-browser-gui.sh), not a copy of the archives: the binding modules are compiled into
# the executable and registered in the inittab under _fcweb names, and pyside-pkg's
# hand-written PySide6/__init__.py aliases those to the dotted names so
# `import PySide6.QtCore` resolves. So nothing in it comes out of this build -- but
# patches/apply.sh only populates the directory `if [ -d ... ]`, and until now nothing
# created it, so the glue was never copied and the preload would have been empty.
PKG="$ROOT/deps/wasm/pyside-pkg"
mkdir -p "$PKG/PySide6" "$PKG/shiboken6"
cp -v "$ROOT/patches/pyside-pkg-glue/PySide6/__init__.py"   "$PKG/PySide6/__init__.py"
cp -v "$ROOT/patches/pyside-pkg-glue/shiboken6/__init__.py" "$PKG/shiboken6/__init__.py"
echo "pyside-pkg: $(find "$PKG" -type f | wc -l | tr -d ' ') file(s)"

echo "=== ARCHIVES ==="
# Report what is actually in each archive, do not just test for one name. The first version
# of this check printed "NO PyInit_QtCore" for all three modules of a build that had just
# linked 694/694 targets cleanly, and could not distinguish "the symbol is absent" from "nm
# never ran" or "the symbol is spelled differently" -- the same class of blind check that has
# already cost this repository four rounds elsewhere.
echo "  nm: ${NM:-<none found>}"
echo "  ar: ${AR:-<none found>}"
pyside_missing=0
check_mod() {   # <archive> <expected PyInit symbol>
    a="$1"; want="$2"
    if [ ! -s "$a" ]; then echo "  MISSING  ${a#$ROOT/}"; pyside_missing=1; return; fi
    if [ -z "$NM" ]; then echo "  ${a#$ROOT/}: present, unverified (no nm)"; return; fi
    out="$("$NM" "$a" 2>&1 | grep -E "PyInit" || true)"
    if [ -z "$out" ]; then
        # Everything needed to tell WHICH of the three it is, in one run: is the module
        # wrapper object in the archive at all, does the archive carry any symbols at all,
        # and if so what do they look like. nm reporting "no symbols" for member after
        # member is not something to theorise about a second time.
        echo "  ${a#$ROOT/}: NO PyInit symbol of any kind."
        echo "        members:            $("$AR" t "$a" 2>/dev/null | wc -l | tr -d ' ')"
        echo "        module wrapper:     $("$AR" t "$a" 2>/dev/null | grep module_wrapper || echo '<<ABSENT>>')"
        echo "        defined symbols:    $("$NM" --defined-only "$a" 2>/dev/null | grep -cE '^[0-9a-fA-F]+ ' || true)"
        echo "        first defined syms:"
        "$NM" --defined-only "$a" 2>/dev/null | grep -E '^[0-9a-fA-F]+ ' | head -8 | sed 's/^/            /'
        echo "        nm, first 3 members:"
        "$NM" "$a" 2>&1 | head -3 | sed 's/^/            /'
        pyside_missing=1
        return
    fi
    echo "  ${a#$ROOT/}: $(printf '%s\n' "$out" | wc -l | tr -d ' ') PyInit symbol(s)"
    printf '%s\n' "$out" | sed 's/^/        /'
    printf '%s\n' "$out" | grep -q "$want" \
        || { echo "        ^^ expected $want and it is not among them"; pyside_missing=1; }
}
check_mod "$ROOT/build-pyside-wasm/PySide6/QtCore/QtCore.abi3.a"       PyInit_QtCore
check_mod "$ROOT/build-pyside-wasm/PySide6/QtGui/QtGui.abi3.a"         PyInit_QtGui
check_mod "$ROOT/build-pyside-wasm/PySide6/QtWidgets/QtWidgets.abi3.a" PyInit_QtWidgets
# libpyside6 and libshiboken6 carry no PyInit_ of their own -- Shiboken's module init comes
# from shibokenmodule's object file, which the link names directly -- so existence is all
# there is to check for these two.
for a in "$ROOT/build-pyside-wasm/libpyside/libpyside6.abi3.a" \
         "$ROOT/deps/wasm/shiboken6/lib/libshiboken6.abi3.a"; do
    if [ -s "$a" ]; then echo "  ok       ${a#$ROOT/}"
    else echo "  MISSING  ${a#$ROOT/}"; pyside_missing=1; fi
done
# Shiboken's own module init, which MainGui.cpp registers as PyInit_Shiboken. The link names
# this object file directly rather than an archive, so check it the same way.
SBKOBJ="$ROOT/build-shiboken-wasm/shibokenmodule/CMakeFiles/shibokenmodule.dir/Shiboken/shiboken_module_wrapper.cpp.o"
if [ -s "$SBKOBJ" ]; then
    echo "  ok       ${SBKOBJ#$ROOT/}"
    [ -n "$NM" ] && "$NM" "$SBKOBJ" 2>&1 | grep -E "PyInit" | sed 's/^/        /'
else
    echo "  MISSING  ${SBKOBJ#$ROOT/}"; pyside_missing=1
fi
[ "$pyside_missing" = 0 ] || {
    echo "ERROR: the PySide build finished but the modules above are not usable" >&2; exit 1; }


# pivy used to be built here. It is not related to PySide -- it needs Coin3D, SWIG and
# CPython, none of which this script touches -- and chaining them meant pivy could not be
# built or fixed without a working PySide toolchain, which is the harder half by a wide
# margin. It now lives in configure-pivy-weh.sh, where it builds on its own.
echo "PYSIDE-LANE-ALL-DONE"
