#!/bin/bash
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
  -DCMAKE_INSTALL_PREFIX="$ROOT/deps/wasm/shiboken6" \
  -DCMAKE_CXX_FLAGS="-pthread -fwasm-exceptions"
ninja -C build-shiboken-wasm install

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
  -DPython_EXECUTABLE="$WASMPY_HOST" -DPython_INCLUDE_DIR="$PYINC" \
  -DPython_LIBRARY="$CPY/builddir/emscripten-mt/libpython3.13.a" -DPython_SOABI=cpython-313-wasm32-emscripten \
  -DCMAKE_INSTALL_PREFIX="$ROOT/emsdk/upstream/emscripten/cache/sysroot" \
  -DCMAKE_CXX_FLAGS="-pthread -fwasm-exceptions"
ninja -C build-pyside-wasm

# pivy used to be built here. It is not related to PySide -- it needs Coin3D, SWIG and
# CPython, none of which this script touches -- and chaining them meant pivy could not be
# built or fixed without a working PySide toolchain, which is the harder half by a wide
# margin. It now lives in configure-pivy-weh.sh, where it builds on its own.
echo "PYSIDE-LANE-ALL-DONE"
