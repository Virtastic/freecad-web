#!/bin/bash
# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) Virtastic
# Port HDF5 1.14.3 to wasm32-emscripten (static, -pthread). Needed by FreeCAD's
# SMESH MED driver and the FEM/MED file format. Pure C — cross-compiles with the
# node emulator running HDF5's small configure-time test programs.
set -e
cd "$(dirname "$0")"
. toolchain/env.sh

# emsdk ships whichever node its installer chose -- 22.16.0 here, 24.19.0 on a hosted
# runner -- so a hardcoded path is a build that only works on one machine. emsdk_env.sh
# exports EMSDK_NODE; fall back to PATH, and fail by name rather than handing cmake a
# CMAKE_CROSSCOMPILING_EMULATOR that does not exist.
FCWEB_NODE="${EMSDK_NODE:-$(command -v node)}"
[ -x "$FCWEB_NODE" ] || { echo "ERROR: no node found (EMSDK_NODE unset and none on PATH)" >&2; exit 1; }

SRC="$ROOT/deps/src/hdf5-1.14.3"
BUILD="$ROOT/build-hdf5"

emcmake cmake -S "$SRC" -B "$BUILD" -G Ninja \
  -DCMAKE_POLICY_VERSION_MINIMUM=3.5 \
  -DCMAKE_BUILD_TYPE=Release \
  -DBUILD_SHARED_LIBS=OFF \
  -DBUILD_STATIC_LIBS=ON \
  -DBUILD_TESTING=OFF \
  -DHDF5_BUILD_TOOLS=OFF \
  -DHDF5_BUILD_EXAMPLES=OFF \
  -DHDF5_BUILD_UTILS=OFF \
  -DHDF5_BUILD_HL_LIB=ON \
  -DHDF5_BUILD_CPP_LIB=OFF \
  -DHDF5_BUILD_FORTRAN=OFF \
  -DHDF5_BUILD_JAVA=OFF \
  -DHDF5_ENABLE_THREADSAFE=OFF \
  -DHDF5_ENABLE_PARALLEL=OFF \
  -DHDF5_ENABLE_Z_LIB_SUPPORT=OFF \
  -DHDF5_ENABLE_SZIP_SUPPORT=OFF \
  -DHDF5_USE_PREGEN=OFF \
  -DHDF5_BATCH_H5DETECT=ON \
  -DCMAKE_INSTALL_PREFIX="$DW" \
  -DCMAKE_C_FLAGS="-fexceptions -pthread -O2" \
  -DCMAKE_CXX_FLAGS="-fexceptions -pthread -O2" \
  -DCMAKE_CROSSCOMPILING_EMULATOR="$FCWEB_NODE"

echo "=== HDF5 configure done; building ==="
ninja -C "$BUILD"
ninja -C "$BUILD" install
echo "=== HDF5 install done ==="
ls "$DW"/lib/libhdf5*.a 2>/dev/null | sed 's#.*/##'
