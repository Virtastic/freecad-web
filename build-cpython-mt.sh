#!/bin/bash
# Rebuild CPython 3.13 emscripten target WITH wasm pthreads (-pthread/atomics)
# so it links cleanly with -pthread OCCT/Boost/Qt. Separate builddir.
set -e
cd "$(dirname "$0")"
. toolchain/env.sh
SRC="$ROOT/deps/src/cpython"
BUILD_PY="$SRC/builddir/build/python.exe"
export EMCC_CFLAGS="-pthread"          # add atomics+bulk-memory to every object
rm -rf "$SRC/builddir/emscripten-mt" && mkdir -p "$SRC/builddir/emscripten-mt"
cd "$SRC/builddir/emscripten-mt"
CONFIG_SITE="$SRC/Tools/wasm/config.site-wasm32-emscripten" \
emconfigure ../../configure -C \
  --host=wasm32-unknown-emscripten \
  --build="$($SRC/config.guess)" \
  --with-emscripten-target=node \
  --with-build-python="$BUILD_PY"
emmake make -j8
echo "=== cpython-mt build done ==="
ls -la libpython3.13.a pyconfig.h 2>/dev/null
