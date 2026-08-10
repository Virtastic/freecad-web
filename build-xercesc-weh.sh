#!/bin/bash
# Build Xerces-C (XML, required by FreeCAD Base) static for wasm (-pthread).
set -e
cd "$(dirname "$0")"
. toolchain/env.sh
emcmake cmake -S deps/src/xercesc -B build-xercesc -G Ninja \
  -DCMAKE_POLICY_VERSION_MINIMUM=3.5 \
  -DCMAKE_BUILD_TYPE=Release \
  -DBUILD_SHARED_LIBS=OFF \
  -Dnetwork=OFF \
  -Dtranscoder=iconv \
  -Dthreads=OFF \
  -DCMAKE_INSTALL_PREFIX="$DW" \
  -DCMAKE_CXX_FLAGS="-fwasm-exceptions -pthread -O2" \
  -DCMAKE_C_FLAGS="-fwasm-exceptions -pthread -O2"
ninja -C build-xercesc
ninja -C build-xercesc install
echo "=== xerces installed ===" && ls "$DW"/lib/libxerces*.a 2>/dev/null
