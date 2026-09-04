#!/usr/bin/env bash
# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) Virtastic
# Link the gmsh wasm module that FreeCAD-Web calls instead of the gmsh binary.
# Run configure-gmsh-weh.sh + `cmake --build build-gmsh-weh --target lib` first.
#
# Produces play-gui/gmsh.{js,wasm}: a MODULARIZEd module fetched on first use, so the
# main FreeCAD.wasm does not grow. Same exception model as the rest of the tree
# (-fwasm-exceptions) — see BUILD-WEH.md.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
source "$ROOT/toolchain/env.sh"
PREFIX="$ROOT/deps/wasm"
BUILD="$ROOT/build-gmsh-weh"
OUT="$ROOT/play-gui"

test -f "$BUILD/libgmsh.a" || { echo "missing $BUILD/libgmsh.a — build the 'lib' target first" >&2; exit 1; }

# OCCT libs, in gmsh's required order (dependency order matters for static linking).
OCC_LIBS=""
for L in TKDESTEP TKDEIGES TKXSBase TKOffset TKFeat TKFillet TKBool TKMesh TKHLR \
         TKBO TKPrim TKShHealing TKTopAlgo TKGeomAlgo TKBRep TKGeomBase TKG3d TKG2d \
         TKMath TKernel; do
  OCC_LIBS="$OCC_LIBS $PREFIX/lib/lib$L.a"
done

em++ -fwasm-exceptions -O2 \
  -I"$ROOT/deps/src/gmsh/api" \
  "$ROOT/gmsh_wasm_main.cpp" \
  "$BUILD/libgmsh.a" \
  $OCC_LIBS \
  -o "$OUT/gmsh.js" \
  -sMODULARIZE=1 \
  -sEXPORT_NAME=GmshModule \
  -sEXPORTED_FUNCTIONS=_fcweb_gmsh_run,_fcweb_gmsh_version,_malloc,_free \
  -sEXPORTED_RUNTIME_METHODS=FS,ccall,cwrap,stringToUTF8,UTF8ToString,lengthBytesUTF8 \
  -sFORCE_FILESYSTEM=1 \
  -sALLOW_MEMORY_GROWTH=1 \
  -sINITIAL_MEMORY=268435456 \
  # 16 GiB, matching the engine. This is a separate wasm module with its own heap, so
  # without an explicit ceiling it would default to 2 GB and gain nothing from wasm64 --
  # which for gmsh is exactly the workload the extra address space is for.
  -sMAXIMUM_MEMORY=17179869184 \
  -sSTACK_SIZE=8MB \
  -sEXIT_RUNTIME=0 \
  -sASSERTIONS=0 \
  -sENVIRONMENT=web,worker \
  -sERROR_ON_UNDEFINED_SYMBOLS=0

ls -la "$OUT/gmsh.js" "$OUT/gmsh.wasm"
echo "gmsh module -> $OUT/gmsh.{js,wasm}"
