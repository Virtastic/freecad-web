#!/bin/bash
# Phase 2: configure FreeCAD core (Base + App + Part) headless for wasm.
# BUILD_GUI=OFF, only Part among Mods. Links our OCCT + CPython(-mt) + Boost + Xerces.
set -e
cd "$(dirname "$0")"
. toolchain/env.sh
CPY="$ROOT/deps/src/cpython"
PYMT="$CPY/builddir/emscripten-mt"           # pthread CPython build
HOSTPY="$CPY/builddir/build/python.exe"
SYSROOT="$(em-config CACHE)/sysroot"

# Link mode: node uses NODERAWFS (host FS); browser preloads resources (set by caller).
: "${FC_LINK_MODE_FLAGS:=-sNODERAWFS=1}"

emcmake cmake -S deps/src/freecad -B build-freecad -G Ninja \
  -DCMAKE_POLICY_VERSION_MINIMUM=3.5 \
  -DCMAKE_PROJECT_INCLUDE_BEFORE="$ROOT/force-static.cmake" \
  -DCMAKE_INSTALL_PREFIX="$ROOT/freecad-install" \
  -DCMAKE_BUILD_TYPE=Release \
  -DBUILD_GUI=OFF \
  -DBUILD_FEM=OFF -DBUILD_ADDONMGR=OFF -DBUILD_BIM=OFF -DBUILD_DRAFT=OFF \
  -DBUILD_HELP=OFF -DBUILD_IDF=OFF -DBUILD_IMPORT=OFF -DBUILD_INSPECTION=OFF \
  -DBUILD_MATERIAL=ON -DBUILD_MESH=OFF -DBUILD_MESH_PART=OFF -DBUILD_FLAT_MESH=OFF \
  -DENABLE_DEVELOPER_TESTS=OFF \
  -DBUILD_OPENSCAD=OFF -DBUILD_PART_DESIGN=OFF -DBUILD_CAM=OFF -DBUILD_ASSEMBLY=OFF \
  -DBUILD_PLOT=OFF -DBUILD_POINTS=OFF -DBUILD_REVERSEENGINEERING=OFF -DBUILD_ROBOT=OFF \
  -DBUILD_SHOW=OFF -DBUILD_SKETCHER=OFF -DBUILD_SPREADSHEET=OFF -DBUILD_START=OFF \
  -DBUILD_TEST=OFF -DBUILD_MEASURE=OFF -DBUILD_TECHDRAW=OFF -DBUILD_TUX=OFF \
  -DBUILD_WEB=OFF -DBUILD_SURFACE=OFF -DBUILD_PART=ON \
  -DBUILD_DYNAMIC_LINK_PYTHON=OFF \
  -DFREECAD_USE_EXTERNAL_PIVY=OFF \
  -DFREECAD_USE_PCH=OFF \
  -DFREECAD_USE_FREETYPE=OFF \
  -DCMAKE_PREFIX_PATH="$DW;$ROOT/qt/6.9.0/wasm_multithread" \
  -DCMAKE_FIND_ROOT_PATH="$DW;$ROOT/qt/6.9.0/wasm_multithread" \
  -DCMAKE_FIND_ROOT_PATH_MODE_PACKAGE=BOTH \
  -DFREECAD_QT_VERSION=6 \
  -DBoost_USE_STATIC_LIBS=ON -DBoost_USE_STATIC_RUNTIME=ON \
  -DQt6_DIR="$ROOT/qt/6.9.0/wasm_multithread/lib/cmake/Qt6" \
  -DQT_HOST_PATH="$ROOT/qt/6.9.0/macos" \
  -DOpenCASCADE_DIR="$DW/lib/cmake/opencascade" \
  -DEIGEN3_INCLUDE_DIR="$DW/include" \
  -DPython3_EXECUTABLE="$HOSTPY" \
  -DPython3_INCLUDE_DIR="$CPY/Include" \
  -DPython3_LIBRARY="$PYMT/libpython3.13.a" \
  -DPYTHON_VERSION_STRING=3.13 \
  -DZLIB_INCLUDE_DIR="$SYSROOT/include" \
  -DZLIB_LIBRARY="$SYSROOT/lib/wasm32-emscripten/libz.a" \
  -DCMAKE_CXX_FLAGS="-fexceptions -pthread -O2 -DBOOST_ALL_NO_LIB --use-port=zlib" \
  -DCMAKE_C_FLAGS="-fexceptions -pthread -O2 --use-port=zlib" \
  -DCMAKE_EXE_LINKER_FLAGS="$FC_LINK_MODE_FLAGS -lembind -pthread -sALLOW_MEMORY_GROWTH -sEXIT_RUNTIME=1 -sPTHREAD_POOL_SIZE=4 -sASSERTIONS=1 -sFORCE_FILESYSTEM=1 --pre-js=$ROOT/pre-env.js --use-port=zlib --use-port=bzip2 --use-port=sqlite3 $PYMT/Modules/_decimal/libmpdec/libmpdec.a $PYMT/Modules/_hacl/libHacl_Hash_SHA2.a $PYMT/Modules/expat/libexpat.a"
