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

# CMake's FindPython reads pyconfig.h out of Python_INCLUDE_DIR to learn the version and
# ABI. CPython's source Include/ does not contain it -- configure GENERATES it into the
# build directory -- so pointing at Include/ alone gives:
#
#     file STRINGS file ".../deps/src/cpython/Include/pyconfig.h" cannot be read
#
# Assemble an include path that has both: Python.h from the source tree, pyconfig.h from
# the WASM build (never the host one, which would misreport the word size).
PYINC="$CPY/Include"
if [ -f "$PYMT/pyconfig.h" ]; then
    PYINC="$PYMT;$CPY/Include"
elif [ -f "$DW/include/python3.13/pyconfig.h" ]; then
    PYINC="$DW/include/python3.13"
else
    echo "!! no wasm pyconfig.h under $PYMT or $DW/include/python3.13 --"
    echo "   FindPython will fail to read it. Check build-cpython-mt.sh ran."
fi
echo "Python include path: $PYINC"

# pivy declares its SWIG target with TYPE MODULE, i.e. a dynamically loaded .so:
#
#     UseSWIG.cmake:973 (add_library): ADD_LIBRARY called with MODULE option but the
#     target platform does not support dynamic linking.
#
# A module is the wrong shape here regardless of what CMake permits. This build links one
# static monolith and registers _coin through MainGui.cpp's inittab, so what is needed is
# an archive. Rewrite the declaration and verify it took, rather than assuming.
SWIG_CM="$SRC/interfaces/CMakeLists.txt"
if [ -f "$SWIG_CM" ] && grep -q 'TYPE MODULE' "$SWIG_CM"; then
    sed -i.orig 's/TYPE MODULE/TYPE STATIC/g' "$SWIG_CM"
    echo "pivy: swig_add_library TYPE MODULE -> STATIC ($(grep -c 'TYPE STATIC' "$SWIG_CM") site(s))"
fi
if [ -f "$SWIG_CM" ] && grep -q 'TYPE MODULE' "$SWIG_CM"; then
    echo "!! still declares TYPE MODULE -- the rewrite did not take"; exit 1
fi

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
    -DPython_INCLUDE_DIR="$PYINC" \
    -DPython_LIBRARY="$PYMT/libpython3.13.a" \
    -DPython3_EXECUTABLE="$CPY/builddir/build/python3-native" \
    -DPython3_INCLUDE_DIR="$PYINC" \
    -DPython3_LIBRARY="$PYMT/libpython3.13.a"

ninja -C build-pivy-wasm

# Find the archive by the symbol the link actually needs, not by filename. Switching the
# target from MODULE to STATIC changes what CMake names the output (a static target gets
# the "lib" prefix), and a check keyed on a filename would report failure for a build that
# succeeded -- or worse, pass on an archive that does not define PyInit__coin.
NM="$ROOT/emsdk/upstream/bin/llvm-nm"
OUT=""
while IFS= read -r a; do
    if "$NM" "$a" 2>/dev/null | grep -q ' T PyInit__coin$'; then OUT="$a"; break; fi
done < <(find build-pivy-wasm -name '*.a')

if [ -z "$OUT" ]; then
    echo "!! no archive under build-pivy-wasm defines PyInit__coin. What was built:"
    find build-pivy-wasm -name '*.a' | sed 's/^/     /' | head
    exit 1
fi

# Stage it under a stable name so the link does not depend on CMake's naming.
mkdir -p "$DW/lib/pivy-mod"
cp "$OUT" "$DW/lib/pivy-mod/lib_coin.a"
echo "pivy built: $OUT"
echo "        -> $DW/lib/pivy-mod/lib_coin.a"
"$NM" "$OUT" 2>/dev/null | grep ' T PyInit' | sed 's/^/  /' || true
