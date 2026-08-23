#!/usr/bin/env bash
# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) Virtastic
# gmsh as a standalone wasm module (its own .wasm, loaded on demand) so FreeCAD's FEM
# workbench can mesh in the browser. FreeCAD drives gmsh through a file boundary
# (write <Part>_Geometry.brep + shape2mesh.geo -> run -> read <name>.unv), so we only
# need gmsh's .geo parser + mesher + OCC BREP import, and none of its GUI.
#
# Must match the rest of the tree: -fwasm-exceptions (see BUILD-WEH.md). Links the
# OCCT we already build for wasm so `Merge "...brep"` in the .geo works.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
source "$ROOT/emsdk/emsdk_env.sh" >/dev/null 2>&1
SRC="$ROOT/deps/src/gmsh"
BUILD="$ROOT/build-gmsh-weh"
PREFIX="$ROOT/deps/wasm"

FLAGS="-fwasm-exceptions -pthread -O2 -DNDEBUG"

# gmsh computes its own OCC_LIBS_REQUIRED list and find_library()s each entry with
# HINTS ENV CASROOT PATH_SUFFIXES lib -- so point CASROOT at our wasm OCCT prefix.
# (Overriding OCC_LIBS_REQUIRED instead just makes the count check disable OCC.)
export CASROOT="$PREFIX"

mkdir -p "$BUILD"
emcmake cmake -S "$SRC" -B "$BUILD" -G Ninja \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_POLICY_VERSION_MINIMUM=3.5 \
  -DCMAKE_C_FLAGS="$FLAGS" \
  -DCMAKE_CXX_FLAGS="$FLAGS" \
  -DCMAKE_INSTALL_PREFIX="$PREFIX" \
  -DENABLE_BUILD_LIB=ON \
  -DENABLE_BUILD_SHARED=OFF \
  -DENABLE_FLTK=OFF \
  -DENABLE_GRAPHICS=OFF \
  -DENABLE_MPI=OFF \
  -DENABLE_OPENMP=OFF \
  -DENABLE_PETSC=OFF \
  -DENABLE_SLEPC=OFF \
  -DENABLE_GETDP=OFF \
  -DENABLE_MED=OFF \
  -DENABLE_CGNS=OFF \
  -DENABLE_HXT=OFF \
  -DENABLE_METIS=OFF \
  -DENABLE_EIGEN=ON \
  -DENABLE_BLAS_LAPACK=OFF \
  -DENABLE_MESH=ON \
  -DENABLE_PARSER=ON \
  -DENABLE_POST=ON \
  -DENABLE_PLUGINS=OFF \
  -DENABLE_ONELAB=OFF \
  -DENABLE_ONELAB_METAMODEL=OFF \
  -DENABLE_OS_SPECIFIC_INSTALL=OFF \
  -DENABLE_OCC=ON \
  -DENABLE_OCC_CAF=OFF \
  -DENABLE_OCC_STATIC=ON \
  -DOCC_INC="$PREFIX/include/opencascade" \
  -DCMAKE_PREFIX_PATH="$PREFIX" \
  -DCMAKE_FIND_ROOT_PATH="$PREFIX" \
  -DCMAKE_FIND_ROOT_PATH_MODE_LIBRARY=BOTH \
  -DCMAKE_FIND_ROOT_PATH_MODE_INCLUDE=BOTH \
  "$@"

echo
echo "configured -> $BUILD"
echo "next: cmake --build $BUILD --target lib -j8"
