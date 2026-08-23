#!/bin/bash
# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) Virtastic
# Phase 1: OCCT 7.8.1 static cross-compile for wasm32-emscripten.
# Mirrors the CS-Web emcmake+Ninja pattern. Headless geometry kernel only.
set -e
cd "$(dirname "$0")"
. toolchain/env.sh

# Materialize + locate the emscripten freetype port (OCCT's only hard dep).
embuilder build freetype >/dev/null 2>&1
CACHE=$(em-config CACHE)
FT_INC="$CACHE/sysroot/include/freetype2"
FT_LIBDIR="$CACHE/sysroot/lib/wasm32-emscripten"

emcmake cmake -S deps/src/occt -B build-occt -G Ninja \
  -DCMAKE_POLICY_VERSION_MINIMUM=3.5 \
  -D3RDPARTY_FREETYPE_INCLUDE_DIR_ft2build="$FT_INC" \
  -D3RDPARTY_FREETYPE_INCLUDE_DIR_freetype2="$FT_INC" \
  -D3RDPARTY_FREETYPE_LIBRARY_DIR="$FT_LIBDIR" \
  -D3RDPARTY_FREETYPE_LIBRARY="$FT_LIBDIR/libfreetype.a" \
  -DCMAKE_BUILD_TYPE=Release \
  -DBUILD_LIBRARY_TYPE=Static \
  -DBUILD_MODULE_Draw=OFF \
  -DBUILD_MODULE_Visualization=OFF \
  -DBUILD_MODULE_ApplicationFramework=ON \
  -DBUILD_MODULE_DataExchange=ON \
  -DBUILD_MODULE_ModelingData=ON \
  -DBUILD_MODULE_ModelingAlgorithms=ON \
  -DUSE_FREETYPE=ON \
  -DUSE_TK=OFF -DUSE_TCL=OFF \
  -DUSE_FREEIMAGE=OFF -DUSE_TBB=OFF -DUSE_VTK=OFF \
  -DUSE_RAPIDJSON=OFF -DUSE_DRACO=OFF -DUSE_FFMPEG=OFF -DUSE_OPENVR=OFF \
  -DUSE_OPENGL=OFF -DUSE_GLES2=ON \
  -DCMAKE_INSTALL_PREFIX="$DW" \
  -DINSTALL_DIR="$DW" \
  -DCMAKE_CXX_FLAGS="-fexceptions -pthread -O3 --use-port=freetype" \
  -DCMAKE_C_FLAGS="-fexceptions -pthread -O3 --use-port=freetype"

echo "=== configure done; building ==="
ninja -C build-occt
ninja -C build-occt install
echo "=== OCCT build+install complete ==="
ls -1 "$DW/lib"/libTK*.a 2>/dev/null | head -40
