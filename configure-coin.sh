#!/bin/bash
# Spike (e): can Coin3D even configure+compile under emscripten? Static lib,
# GLES/WebGL2 target, force-include the reused gl_compat.h shim.
set -e
cd "$(dirname "$0")"
. toolchain/env.sh

emcmake cmake -S deps/src/coin3d -B build-coin -G Ninja \
  -DCMAKE_POLICY_VERSION_MINIMUM=3.5 \
  -DCMAKE_BUILD_TYPE=Release \
  -DBUILD_SHARED_LIBS=OFF \
  -DCOIN_BUILD_SHARED_LIBS=OFF \
  -DCOIN_BUILD_TESTS=OFF \
  -DCOIN_BUILD_DOCUMENTATION=OFF \
  -DCOIN_BUILD_GLX=OFF \
  -DCOIN_BUILD_EGL=OFF \
  -DCMAKE_DISABLE_FIND_PACKAGE_X11=ON \
  -DCMAKE_INSTALL_PREFIX="$DW" \
  -DCMAKE_CXX_FLAGS="-fexceptions -pthread -O2 -DGLES_SILENCE_DEPRECATION -include $DW/include/gl_compat.h" \
  -DCMAKE_C_FLAGS="-fexceptions -pthread -O2 -include $DW/include/gl_compat.h" \
  -DOPENGL_INCLUDE_DIR="$(em-config CACHE)/sysroot/include" \
  -DOPENGL_gl_LIBRARY="GL" \
  2>&1 | tail -25
