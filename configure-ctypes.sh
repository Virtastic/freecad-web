#!/bin/bash
# Build libffi (pyodide's wasm-capable fork) + CPython _ctypes for wasm.
# Enables the `ctypes` stdlib module (and thus matplotlib's interactive QtAgg
# canvas). libffi creates function-table entries at runtime for closures, so the
# final FreeCAD link needs -sALLOW_TABLE_GROWTH (added in configure-gui.sh).
set -e
cd "$(dirname "$0")"
ROOT="$PWD"; DW="$ROOT/deps/wasm"
source emsdk/emsdk_env.sh >/dev/null 2>&1

# 1. libffi (needs automake for autogen)
if [ ! -d deps/src/libffi ]; then
  git clone --depth 1 https://github.com/hoodmane/libffi-emscripten.git deps/src/libffi
fi
cd deps/src/libffi
[ -f configure ] || ./autogen.sh
emconfigure ./configure --host=wasm32-unknown-emscripten --enable-static --disable-shared \
  --disable-dependency-tracking CFLAGS="-fPIC -O2 -fexceptions -pthread"
emmake make -j4 libffi.la   # 'make' fails on docs (texinfo); build just the lib
FFI="$PWD/wasm32-unknown-emscripten"
cp "$FFI/.libs/libffi.a" "$DW/lib/libffi.a"
cp "$FFI/include/ffi.h" "$FFI/include/ffitarget.h" "$DW/include/"
cd "$ROOT"

# 2. CPython _ctypes module against libffi
CT="$ROOT/deps/src/cpython/Modules/_ctypes"
OUT=/tmp/ctbuild; mkdir -p "$OUT"; rm -f "$OUT"/*.o
FLAGS=(-c -O2 -fexceptions -pthread -fPIC
  -DHAVE_FFI_PREP_CIF_VAR -DHAVE_FFI_PREP_CLOSURE_LOC -DHAVE_FFI_CLOSURE_ALLOC -DPy_BUILD_CORE_MODULE
  -I"$DW/include" -I"$ROOT/deps/src/cpython/Include" -I"$ROOT/deps/src/cpython/builddir/emscripten-mt"
  -I"$ROOT/deps/src/cpython/Include/internal" -I"$CT")
for src in _ctypes callbacks callproc stgdict cfield malloc_closure; do
  emcc "${FLAGS[@]}" "$CT/$src.c" -o "$OUT/$src.o"
done
mkdir -p "$DW/lib/ctypes-mod"
"$ROOT/emsdk/upstream/emscripten/emar" rcs "$DW/lib/ctypes-mod/lib_ctypes.a" "$OUT"/*.o
echo "_ctypes built (PyInit__ctypes):"
"$ROOT/emsdk/upstream/emscripten/emnm" "$DW/lib/ctypes-mod/lib_ctypes.a" | grep 'T PyInit'
