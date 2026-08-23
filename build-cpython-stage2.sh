#!/bin/bash
# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) Virtastic
# CPython stage 2 only: emscripten cross build using the already-built host python.exe.
set -e
cd "$(dirname "$0")"
. toolchain/env.sh
SRC="$ROOT/deps/src/cpython"
BUILD_PY="$SRC/builddir/build/python.exe"
rm -rf "$SRC/builddir/emscripten" && mkdir -p "$SRC/builddir/emscripten"
cd "$SRC/builddir/emscripten"
CONFIG_SITE="$SRC/Tools/wasm/config.site-wasm32-emscripten" \
emconfigure ../../configure -C \
  --host=wasm32-unknown-emscripten \
  --build="$($SRC/config.guess)" \
  --with-emscripten-target=node \
  --with-build-python="$BUILD_PY"
emmake make -j6
echo "=== cpython emscripten build done ==="
ls -la libpython3.13.a pyconfig.h 2>/dev/null
