#!/bin/bash
# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) Virtastic
# Port IfcOpenShell 0.8.6 to wasm32-emscripten for real IFC in FreeCAD's BIM/Arch
# (replaces the ifcopenshell stub). Builds IfcParse (schema parser) + IfcGeom
# (geometry over OUR wasm OCCT 7.8.1 — exact version match) + the SWIG Python
# wrapper as a static module (inittab like pivy/_coin). Uses OUR emsdk 3.1.70 +
# CPython, and -fwasm-exceptions (emscripten EH) to match the FreeCAD ABI — NOT the
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
# CPython's host build is python.exe on macOS and python (or python3-native) on Linux, so
# a single hardcoded name is a script that runs on one machine. Take the first that exists.
HOSTPY=""
for c in "$CPY/builddir/build/python.exe" "$CPY/builddir/build/python" \
         "$CPY/builddir/build/python3-native"; do
    [ -x "$c" ] && { HOSTPY="$c"; break; }
done
[ -n "$HOSTPY" ] || { echo "!! no host python under $CPY/builddir/build -- run build-cpython.sh"; exit 1; }
echo "host python: $HOSTPY"

# Same trap pivy hit: CMake reads pyconfig.h out of the include dir to learn the ABI, and
# CPython generates it into the build tree rather than shipping it in Include/. It has to
# be ONE directory holding both, so assemble one -- with the WASM pyconfig.h, never the
# host's, which would report the wrong word size.
PYINC="$ROOT/build-pyinc-wasm"
if [ ! -f "$PYINC/pyconfig.h" ] || [ ! -f "$PYINC/Python.h" ]; then
    if [ -f "$PYMT/pyconfig.h" ]; then
        rm -rf "$PYINC" && mkdir -p "$PYINC"
        cp -r "$CPY/Include/." "$PYINC/"
        cp "$PYMT/pyconfig.h" "$PYINC/pyconfig.h"
    else
        echo "!! no wasm pyconfig.h under $PYMT -- run build-cpython-mt.sh"; exit 1
    fi
fi
echo "python include dir: $PYINC"

# IfcGeom includes <Eigen/Dense>, so EIGEN_DIR must be the directory CONTAINING Eigen/,
# not a generic include root. deps/wasm/include has no Eigen in it at all -- Eigen is
# header-only and nothing stages it there -- so the previous value was wrong on every
# machine. It simply was not reached until a compile got deep enough to say:
#     taxonomy.h:13:10: fatal error: 'Eigen/Dense' file not found
EIGEN_DIR=""
for d in "$ROOT/deps/src/eigen" "$DW/include/eigen3" "$DW/include"; do
    [ -f "$d/Eigen/Dense" ] && { EIGEN_DIR="$d"; break; }
done
[ -n "$EIGEN_DIR" ] || {
    echo "!! no Eigen/Dense found. Looked in:"
    echo "     $ROOT/deps/src/eigen"
    echo "     $DW/include/eigen3"
    echo "     $DW/include"
    echo "   Fetch Eigen 3.4.0 the way build-freecad.yml does."
    exit 1; }
echo "eigen dir: $EIGEN_DIR"

# OpaqueCoordinate's forwarding constructor is unconstrained and hijacks copy-construction
# from non-const lvalues, which is exactly what SWIG's generated wrapper does. Without this
# the Python bindings do not compile at all. Idempotent; see the tool for the full account.
python3 "$ROOT/tools/patch-ifcopenshell.py" "$SRC"

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
  -DEIGEN_DIR="$EIGEN_DIR" \
  -DSWIG_EXECUTABLE="$(command -v swig)" \
  -DPYTHON_EXECUTABLE="$HOSTPY" \
  -DPYTHON_INCLUDE_DIR="$PYINC" \
  -DPYTHON_LIBRARY="$PYMT/libpython3.13.a" \
  -DCMAKE_PREFIX_PATH="$DW" \
  -DCMAKE_FIND_ROOT_PATH="$DW" \
  -DCMAKE_C_FLAGS="-fwasm-exceptions -pthread -O2" \
  -DCMAKE_CXX_FLAGS="-fwasm-exceptions -pthread -O2 -DBOOST_ALL_NO_LIB -I$DW/include" \
  -DCMAKE_CROSSCOMPILING_EMULATOR="$FCWEB_NODE"

echo "=== IfcOpenShell configure done; building ==="
ninja -C "$BUILD"
echo "=== build done ==="

# MainGui.cpp registers _ifcopenshell_wrapper in its inittab, so the archive defining
# PyInit__ifcopenshell_wrapper is the one that matters. Find it by symbol rather than by
# filename, and stage it under a stable name: with -sERROR_ON_UNDEFINED_SYMBOLS=0 a missing
# archive is not a link error, it is a trapping PyInit_* the first time BIM imports IFC.
NM="$ROOT/emsdk/upstream/bin/llvm-nm"
WRAP=""
while IFS= read -r a; do
    if "$NM" "$a" 2>/dev/null | grep -q ' T PyInit__ifcopenshell_wrapper$'; then WRAP="$a"; break; fi
done < <(find "$BUILD" \( -name '*.a' -o -name '*.so' \))

if [ -z "$WRAP" ]; then
    echo "!! no archive defines PyInit__ifcopenshell_wrapper. What was built:"
    find "$BUILD" \( -name '*.a' -o -name '*.so' \) | sed 's#.*/#     #' | sort | head -30
    exit 1
fi

mkdir -p "$DW/lib/ifc-mod"
cp "$WRAP" "$DW/lib/ifc-mod/lib_ifcopenshell_wrapper.a"
# EVERY archive the build produced, not an enumerated subset. The list this replaces --
# libIfcParse, libIfcGeom*, libgeometry_*, libSerializers -- missed whatever defines the
# per-schema XML serializer entry points, and the FreeCAD link ended in
#     libSerializers.a(XmlSerializer.cpp.o): undefined symbol: init_XmlSerializer_Ifc4x3_add2
# Enumerating another project's internal library names goes stale silently; take them all
# and let --start-group sort out the order.
for a in $(find "$BUILD" -name '*.a' | sort); do
    case "$(basename "$a")" in
        lib_ifcopenshell_wrapper.a) continue ;;   # already staged, under its canonical name
    esac
    cp "$a" "$DW/lib/ifc-mod/"
done
# v1 staged an enumerated subset; v2 stages every archive the build produced.
echo 2 > "$DW/lib/ifc-mod/.staged"
echo "IfcOpenShell staged to $DW/lib/ifc-mod:"
ls -la "$DW/lib/ifc-mod" | sed 's/^/    /'
"$NM" "$WRAP" 2>/dev/null | grep ' T PyInit' | sed 's/^/  /' || true
