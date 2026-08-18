#!/bin/bash
# Port IfcOpenShell 0.8.6 to wasm32-emscripten for real IFC in FreeCAD's BIM/Arch
# (replaces the ifcopenshell stub). Builds IfcParse (schema parser) + IfcGeom
# (geometry over OUR wasm OCCT 7.8.1 — exact version match) + the SWIG Python
# wrapper as a static module (inittab like pivy/_coin). Uses OUR emsdk 3.1.70 +
# CPython, and -fexceptions (emscripten EH) to match the FreeCAD ABI — NOT the
# pyodide default -fwasm-exceptions (would be an incompatible EH ABI).
set -e
cd "$(dirname "$0")"
. toolchain/env.sh

# emsdk ships whichever node its installer chose -- 22.16.0 here, 24.19.0 on a hosted
# runner -- so a hardcoded path is a build that only works on one machine. emsdk_env.sh
# exports EMSDK_NODE; fall back to PATH, and fail by name rather than handing cmake a
# CMAKE_CROSSCOMPILING_EMULATOR that does not exist.
FCWEB_NODE="${EMSDK_NODE:-$(command -v node)}"
[ -x "$FCWEB_NODE" ] || { echo "ERROR: no node found (EMSDK_NODE unset and none on PATH)" >&2; exit 1; }

SRC="$ROOT/deps/src/ifcopenshell"
BUILD="$ROOT/build-ifcopenshell"
CPY="$ROOT/deps/src/cpython"
PYMT="$CPY/builddir/emscripten-mt"
HOSTPY="$CPY/builddir/build/python.exe"

# IfcOpenShell's cmake root is src/cmake/../cmake (the top cmake/ dir points at src via WASM logic);
# the actual CMakeLists is deps/src/ifcopenshell/cmake/CMakeLists.txt.
emcmake cmake -S "$SRC/cmake" -B "$BUILD" -G Ninja \
  -DCMAKE_POLICY_VERSION_MINIMUM=3.5 \
  -DCMAKE_BUILD_TYPE=Release \
  -DWASM_BUILD=ON \
  -DBUILD_SHARED_LIBS=OFF \
  -DBUILD_IFCGEOM=ON \
  -DBUILD_IFCPYTHON=ON \
  -DBUILD_CONVERT=OFF \
  -DBUILD_GEOMSERVER=OFF \
  -DBUILD_EXAMPLES=OFF \
  -DWITH_OPENCASCADE=ON \
  -DWITH_CGAL=OFF \
  -DCOLLADA_SUPPORT=OFF \
  -DGLTF_SUPPORT=OFF \
  -DHDF5_SUPPORT=OFF \
  -DIFCXML_SUPPORT=OFF \
  -DOCC_INCLUDE_DIR="$DW/include/opencascade" \
  -DOCC_LIBRARY_DIR="$DW/lib" \
  -DBOOST_ROOT="$DW" \
  -DBoost_INCLUDE_DIR="$DW/include" \
  -DBoost_USE_STATIC_LIBS=ON \
  -DEIGEN_DIR="$DW/include" \
  -DSWIG_EXECUTABLE="$(command -v swig)" \
  -DPYTHON_EXECUTABLE="$HOSTPY" \
  -DPYTHON_INCLUDE_DIR="$CPY/Include" \
  -DPYTHON_LIBRARY="$PYMT/libpython3.13.a" \
  -DCMAKE_PREFIX_PATH="$DW" \
  -DCMAKE_FIND_ROOT_PATH="$DW" \
  -DCMAKE_C_FLAGS="-fexceptions -pthread -O2" \
  -DCMAKE_CXX_FLAGS="-fexceptions -pthread -O2 -DBOOST_ALL_NO_LIB -I$DW/include" \
  -DCMAKE_CROSSCOMPILING_EMULATOR="$FCWEB_NODE"

echo "=== IfcOpenShell configure done; building ==="
ninja -C "$BUILD"
echo "=== build done ==="
find "$BUILD" -name "*.a" | sed 's#.*/##'
