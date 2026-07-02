#!/bin/bash
# Spike (c) prerequisite: cross-build CPython 3.13 for wasm32-emscripten (node
# target = threads + direct FS). Produces libpython3.13.a + pyconfig.h to embed.
set -e
cd "$(dirname "$0")"
. toolchain/env.sh
SRC="$ROOT/deps/src/cpython"
cd "$SRC"

# Stage 1: host (build) interpreter, same source tree/version.
if [ ! -x "$SRC/builddir/build/python" ] && [ ! -x "$SRC/builddir/build/python.exe" ]; then
  echo "=== stage 1: host python ==="
  mkdir -p builddir/build
  ( cd builddir/build && ../../configure -C >/dev/null && make -j8 )
fi
BUILD_PY="$SRC/builddir/build/python"
[ -x "$BUILD_PY" ] || BUILD_PY="$SRC/builddir/build/python.exe"
echo "host python: $BUILD_PY"

# Stage 2: emscripten cross build (node flavor).
echo "=== stage 2: emscripten cross build ==="
mkdir -p builddir/emscripten
cd builddir/emscripten
CONFIG_SITE="$SRC/Tools/wasm/config.site-wasm32-emscripten" \
emconfigure ../../configure -C \
  --host=wasm32-unknown-emscripten \
  --build="$($SRC/config.guess)" \
  --with-emscripten-target=node \
  --with-build-python="$BUILD_PY"
emmake make -j8
echo "=== cpython emscripten build done ==="
ls -la libpython3.13.a pyconfig.h 2>/dev/null
