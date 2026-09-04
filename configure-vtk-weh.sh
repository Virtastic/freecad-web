#!/bin/bash
# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) Virtastic
# Port VTK 9.3.1 to wasm64-emscripten (static, -pthread to match the FreeCAD
# stack). Minimal module set: just what FreeCAD's bundled SMESH (salomesmesh)
# needs — the vtkUnstructuredGrid data model + mesh-quality filter + legacy IO.
# No rendering, no wrapping (so no host compile-tools build required).
set -e
cd "$(dirname "$0")"
. toolchain/env.sh

# emsdk ships whichever node its installer chose -- 22.16.0 here, 24.19.0 on a hosted
# runner -- so a hardcoded path is a build that only works on one machine. emsdk_env.sh
# exports EMSDK_NODE; fall back to PATH, and fail by name rather than handing cmake a
# CMAKE_CROSSCOMPILING_EMULATOR that does not exist.
FCWEB_NODE="${EMSDK_NODE:-$(command -v node)}"
[ -x "$FCWEB_NODE" ] || { echo "ERROR: no node found (EMSDK_NODE unset and none on PATH)" >&2; exit 1; }

SRC="$ROOT/deps/src/VTK-9.3.1"
BUILD="$ROOT/build-vtk"

emcmake cmake -S "$SRC" -B "$BUILD" -G Ninja \
  -DCMAKE_POLICY_VERSION_MINIMUM=3.5 \
  -DCMAKE_BUILD_TYPE=Release \
  `# expat's XML_Index width has to match on both sides of the call, or wasm-ld` \
  `# resolves the mismatch to a trapping stub and every .vtu read dies with` \
  `# "RuntimeError: unreachable" -- which is what opening the shipped FEMExample` \
  `# did. Two flags used to force 64-bit here, and could not work: vtkexpat's own` \
  `# CMakeLists forces EXPAT_LARGE_SIZE OFF under Emscripten, so the library stayed` \
  `# 32-bit while its C consumers went 64-bit, and the C++ consumers -- including` \
  `# vtkXMLParser.cxx, where the trap lands -- never saw the define at all. The` \
  `# flags made the mismatch rather than fixing it.` \
  `# patches/vtk-expat-wasm-xmlsize.patch settles it the other way, keeping both` \
  `# halves at 32-bit, and patches/apply.sh now applies it.` \
  -DBUILD_SHARED_LIBS=OFF \
  -DVTK_ENABLE_WRAPPING=OFF \
  -DVTK_WRAP_PYTHON=OFF \
  -DVTK_BUILD_TESTING=OFF \
  -DVTK_BUILD_EXAMPLES=OFF \
  -DVTK_BUILD_DOCUMENTATION=OFF \
  -DVTK_ENABLE_KITS=OFF \
  -DVTK_ENABLE_LOGGING=OFF \
  -DVTK_ENABLE_REMOTE_MODULES=OFF \
  -DVTK_LEGACY_REMOVE=ON \
  -DVTK_USE_CUDA=OFF -DVTK_USE_MPI=OFF \
  -DVTK_GROUP_ENABLE_Rendering=DONT_WANT \
  -DVTK_GROUP_ENABLE_Qt=DONT_WANT \
  -DVTK_GROUP_ENABLE_Views=DONT_WANT \
  -DVTK_GROUP_ENABLE_Web=DONT_WANT \
  -DVTK_GROUP_ENABLE_Imaging=DONT_WANT \
  -DVTK_GROUP_ENABLE_MPI=DONT_WANT \
  -DVTK_GROUP_ENABLE_StandAlone=DONT_WANT \
  -DVTK_MODULE_ENABLE_VTK_CommonCore=YES \
  -DVTK_MODULE_ENABLE_VTK_CommonDataModel=YES \
  -DVTK_MODULE_ENABLE_VTK_CommonSystem=YES \
  -DVTK_MODULE_ENABLE_VTK_CommonMath=YES \
  -DVTK_MODULE_ENABLE_VTK_CommonMisc=YES \
  -DVTK_MODULE_ENABLE_VTK_CommonTransforms=YES \
  -DVTK_MODULE_ENABLE_VTK_CommonExecutionModel=YES \
  -DVTK_MODULE_ENABLE_VTK_FiltersCore=YES \
  -DVTK_MODULE_ENABLE_VTK_FiltersGeneral=YES \
  -DVTK_MODULE_ENABLE_VTK_FiltersVerdict=YES \
  -DVTK_MODULE_ENABLE_VTK_FiltersGeometry=YES \
  -DVTK_MODULE_ENABLE_VTK_FiltersExtraction=YES \
  -DVTK_MODULE_ENABLE_VTK_FiltersModeling=YES \
  -DVTK_MODULE_ENABLE_VTK_FiltersSources=YES \
  -DVTK_MODULE_ENABLE_VTK_IOCore=YES \
  -DVTK_MODULE_ENABLE_VTK_IOLegacy=YES \
  -DVTK_MODULE_ENABLE_VTK_IOXML=YES \
  -DVTK_MODULE_ENABLE_VTK_IOXMLParser=YES \
  -DCMAKE_INSTALL_PREFIX="$DW" \
  -DCMAKE_C_FLAGS="-fwasm-exceptions -pthread -O2" \
  # -DFMT_USE_CHAR8_T=0: VTK 9.3.1 vendors an old fmt whose basic_string_view<char8_t>
  # instantiates std::char_traits<fmt::char8_t>. The libc++ in emsdk 6.0.9 no longer
  # provides a char_traits primary template to instantiate, so ThirdParty/diy2 fails with
  #   note: in instantiation of member function fmt::basic_string_view<fmt::char8_t>
  #   note: template is declared here -- struct char_traits;
  # fmt gates the whole char8_t path on this macro, so turning it off skips the
  # specialisation. It is a toolchain incompatibility, not a wasm64 one: the same VTK
  # against the same libc++ fails identically at wasm32.
  -DCMAKE_CXX_FLAGS="-fwasm-exceptions -pthread -O2 -DFMT_USE_CHAR8_T=0" \
  -DCMAKE_CROSSCOMPILING_EMULATOR="$FCWEB_NODE"

echo "=== VTK configure done; building ==="
ninja -C "$BUILD"
ninja -C "$BUILD" install
echo "=== VTK install done ==="
ls "$DW"/lib/libvtk*.a 2>/dev/null | sed 's#.*/##'
