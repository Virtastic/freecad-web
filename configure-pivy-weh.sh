#!/bin/bash
# Cross-compile pivy (the SWIG Coin3D bindings) to wasm32-emscripten, producing the
# _coin.a that MainGui.cpp registers as the builtin `_coin` module.
#
# Extracted from rebuild-pyside-weh.sh, which builds shiboken, PySide AND pivy in one
# pass. They are not related: pivy needs Coin3D, SWIG and CPython; PySide needs Qt and a
# host libclang. Chaining them means pivy cannot be built or fixed without also having a
# working PySide toolchain, which is the harder half by a wide margin. The pivy portion is
# unchanged -- same flags, same force-include.
set -e
cd "$(dirname "$0")"
ROOT="$PWD"
DW="$ROOT/deps/wasm"
SRC="$ROOT/deps/src/pivy"

[ -d "$SRC" ] || { echo "!! $SRC missing -- fetch pivy first"; exit 1; }
[ -s "$DW/lib/libCoin.a" ] || { echo "!! $DW/lib/libCoin.a missing -- build Coin3D first"; exit 1; }
[ -s "$DW/include/gl_compat.h" ] || { echo "!! $DW/include/gl_compat.h missing -- run toolchain/stage-headers.sh"; exit 1; }
command -v swig >/dev/null 2>&1 || { echo "!! swig not on PATH -- pivy is SWIG-generated"; exit 1; }

if [ -f "$ROOT/.qtvenv/bin/activate" ]; then
    # shellcheck disable=SC1091
    source "$ROOT/.qtvenv/bin/activate"
fi
# shellcheck disable=SC1091
source "$ROOT/emsdk/emsdk_env.sh" >/dev/null 2>&1

CPY="$ROOT/deps/src/cpython"
PYMT="$CPY/builddir/emscripten-mt"

# gl_compat.h is force-included for the same reason Coin itself needs it: pivy compiles
# against Coin's headers, which reference the legacy fixed-function GL entry points.
PIVYFLAGS="-pthread -fwasm-exceptions -O2 -include $DW/include/gl_compat.h"

rm -rf build-pivy-wasm
emcmake cmake -S "$SRC" -B build-pivy-wasm -G Ninja \
    -DCMAKE_POLICY_VERSION_MINIMUM=3.5 \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_CXX_FLAGS="$PIVYFLAGS" \
    -DCMAKE_MODULE_PATH="$ROOT/toolchain/cmake" \
    -DCMAKE_PREFIX_PATH="$DW" \
    -DCMAKE_FIND_ROOT_PATH="$DW" \
    -DCMAKE_FIND_ROOT_PATH_MODE_PACKAGE=BOTH \
    -DCOIN3D_INCLUDE_DIRS="$DW/include" \
    -DCOIN3D_LIBRARIES="$DW/lib/libCoin.a" \
    -DPython_EXECUTABLE="$CPY/builddir/build/python3-native" \
    -DPython_INCLUDE_DIR="$CPY/Include" \
    -DPython_LIBRARY="$PYMT/libpython3.13.a" \
    -DPython3_EXECUTABLE="$CPY/builddir/build/python3-native" \
    -DPython3_INCLUDE_DIR="$CPY/Include" \
    -DPython3_LIBRARY="$PYMT/libpython3.13.a"

ninja -C build-pivy-wasm

# The link names build-pivy-wasm/interfaces/_coin.a directly, so check for it by name
# rather than trusting ninja's exit status.
OUT="$ROOT/build-pivy-wasm/interfaces/_coin.a"
if [ ! -s "$OUT" ]; then
    echo "!! $OUT not produced. What the build did make:"
    find build-pivy-wasm -name '*.a' | sed 's/^/     /' | head
    exit 1
fi
echo "pivy built: $OUT"
"$ROOT/emsdk/upstream/bin/llvm-nm" "$OUT" 2>/dev/null | grep ' T PyInit' | sed 's/^/  /' || true
