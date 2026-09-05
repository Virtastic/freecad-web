#!/bin/bash
# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) Virtastic
# Phase 3: configure FreeCAD WITH GUI (BUILD_GUI=ON) for wasm.
# PySide/Shiboken OFF (don't exist for wasm); Coin3D viewport via bundled Quarter.
set -e
cd "$(dirname "$0")"
. toolchain/env.sh
CPY="$ROOT/deps/src/cpython"
PYMT="$CPY/builddir/emscripten-mt"
SYSROOT="$(em-config CACHE)/sysroot"
: "${FC_LINK_MODE_FLAGS:=-sNODERAWFS=1}"

# ---- Host-machine paths --------------------------------------------------------------
# Everything below used to name ONE machine: python.exe (a macOS-only name for CPython's
# host build), qt/6.9.0/macos, and a pybind11 under .qtvenv/lib/python3.14. That is the
# same defect the numpy, pivy, IfcOpenShell and PySide lanes each hit separately -- a
# configure that only runs where it was written. Resolve each, and fail naming what is
# missing rather than handing cmake a path that does not exist.

# CPython's host build: python.exe on macOS, python or python3-native elsewhere.
HOSTPY=""
for c in "$CPY/builddir/build/python.exe" "$CPY/builddir/build/python" \
         "$CPY/builddir/build/python3-native"; do
    [ -x "$c" ] && { HOSTPY="$c"; break; }
done
[ -n "$HOSTPY" ] || { echo "ERROR: no CPython host build under $CPY/builddir/build" >&2; exit 1; }
echo "cpython host: $HOSTPY"

# Host Qt: the wasm build needs the native tools (moc, rcc, qmake). build-qt-wasm.yml
# installs them to qt-host/6.11.2/gcc_64 on Linux; the build machine has qt/6.11.2/macos.
QT_HOST=""
for d in "$ROOT/qt-host/6.11.2/gcc_64" "$ROOT/qt/6.11.2/macos" "$ROOT/qt/6.11.2/gcc_64" \
         "$ROOT/qt-host/6.11.2/macos"; do
    if [ -x "$d/bin/qmake" ] || [ -x "$d/bin/moc" ]; then QT_HOST="$d"; break; fi
done
[ -n "$QT_HOST" ] || { echo "ERROR: no host Qt found (looked for bin/qmake under qt-host/6.11.2/gcc_64, qt/6.11.2/macos, ...)" >&2; exit 1; }
echo "host Qt:      $QT_HOST"

# pybind11's cmake package. Ask whichever interpreter has it rather than naming a
# site-packages path with a Python version baked into it.
PYBIND11_DIR="${FCWEB_PYBIND11_DIR:-}"
if [ -z "$PYBIND11_DIR" ]; then
    for py in "$ROOT/.qtvenv/bin/python3" python3 python; do
        command -v "$py" >/dev/null 2>&1 || [ -x "$py" ] || continue
        PYBIND11_DIR="$("$py" -m pybind11 --cmakedir 2>/dev/null || true)"
        [ -n "$PYBIND11_DIR" ] && [ -d "$PYBIND11_DIR" ] && break
        PYBIND11_DIR=""
    done
fi
if [ -z "$PYBIND11_DIR" ]; then
    PYBIND11_DIR="$(ls -d "$ROOT"/.qtvenv/lib/python3.*/site-packages/pybind11/share/cmake/pybind11 2>/dev/null | head -1)"
fi
[ -n "$PYBIND11_DIR" ] && [ -d "$PYBIND11_DIR" ] || {
    echo "ERROR: pybind11 cmake dir not found. FreeCAD 1.1 needs it (FREECAD_USE_PYBIND11=ON)." >&2
    echo "       Install it (pip install pybind11) or set FCWEB_PYBIND11_DIR." >&2
    exit 1; }
echo "pybind11:     $PYBIND11_DIR"

# CMake's FindPython reads pyconfig.h out of Python3_INCLUDE_DIR, and CPython does not ship
# it in Include/ -- configure generates it into the build tree. Assemble one directory
# holding both, exactly as the numpy, matplotlib, pivy, IfcOpenShell and PySide lanes each
# had to. The WASM pyconfig.h, never the host's, or every target unit fails on LONG_BIT.
PYINC="$CPY/Include"
if [ ! -f "$CPY/Include/pyconfig.h" ]; then
    PYINC="$ROOT/build-pyinc-wasm"
    if [ ! -f "$PYINC/Python.h" ] || [ ! -f "$PYINC/pyconfig.h" ]; then
        [ -f "$PYMT/pyconfig.h" ] || { echo "ERROR: no wasm pyconfig.h under $PYMT" >&2; exit 1; }
        rm -rf "$PYINC" && mkdir -p "$PYINC"
        cp -r "$CPY/Include/." "$PYINC/"
        cp "$PYMT/pyconfig.h" "$PYINC/pyconfig.h"
    fi
fi
echo "python inc:   $PYINC"

# Eigen is header-only, and where it lives differs by machine: the build machine has it
# under deps/wasm/include, CI fetches the release tarball to deps/src/eigen. FindEigen3
# reports "version .. found" with an EMPTY version and then refuses when the directory has
# no Eigen in it, which reads as a version problem and is not.
EIGEN_INC=""
for d in "$DW/include" "$ROOT/deps/src/eigen" "$DW/include/eigen3"; do
    [ -f "$d/Eigen/Core" ] && { EIGEN_INC="$d"; break; }
done
[ -n "$EIGEN_INC" ] || { echo "ERROR: no Eigen (looked for Eigen/Core under $DW/include, deps/src/eigen)" >&2; exit 1; }
echo "eigen:        $EIGEN_INC"

# FreeType, same problem as Eigen. FREECAD_USE_FREETYPE=ON is not optional -- without it
# Part.makeWireString() raises "FreeCAD compiled without FreeType support!" and Draft
# ShapeString stops working -- and the only freetype here is the one matplotlib builds as a
# meson subproject. This used to point at deps/src/matplotlib/subprojects/.../include, a
# SOURCE tree nothing caches, which cost 4478 compiled targets before
#     src/Mod/Part/App/FT2FC.cpp:65:11: fatal error: 'ft2build.h' file not found
# configure-matplotlib-weh.sh now stages the headers to deps/wasm/include/freetype2; prefer
# those, fall back to the source tree.
FT_INC=""
for d in "$DW/include/freetype2" "$ROOT/deps/src/matplotlib/subprojects/freetype-2.6.1/include"          "$DW/include"; do
    [ -f "$d/ft2build.h" ] && { FT_INC="$d"; break; }
done
[ -n "$FT_INC" ] || {
    echo "ERROR: no ft2build.h (looked in $DW/include/freetype2 and matplotlib's subproject)." >&2
    echo "       Run configure-matplotlib-weh.sh first -- it builds and stages freetype." >&2
    exit 1; }
echo "freetype:     $FT_INC"

# IfcOpenShell's archives, taken from the directory rather than from a list. The list this
# replaces named libgeometry_kernel_opencascade.a, which THIS build of IfcOpenShell does not
# produce at all -- and omitted libgeometry_mapping_ifc2x3/ifc4/ifc4x3_add2 and
# libgeometry_serializer_ifc*, which it does, and which are the per-schema IFC support. A
# hardcoded list of another project's internal library names goes stale silently; the numpy,
# matplotlib, kiwisolver, ctypes and PIL sets are all globbed here for the same reason.
# The wrapper goes first because it carries PyInit__ifcopenshell_wrapper; the rest are
# inside --start-group/--end-group, so their order does not matter.
IFCLIBS=""
if [ -d "$DW/lib/ifc-mod" ]; then
  IFCLIBS="$( { ls "$DW"/lib/ifc-mod/lib_ifcopenshell_wrapper.a 2>/dev/null;                 ls "$DW"/lib/ifc-mod/*.a 2>/dev/null | grep -v 'lib_ifcopenshell_wrapper\.a'; }               | tr '
' ' ')"
fi
echo "ifcopenshell: $(printf '%s' "$IFCLIBS" | wc -w | tr -d ' ') archive(s)"

# ---- Heap size -------------------------------------------------------------------------
# 16 GiB ceiling, growing from 1 GiB. This is a wasm64 build, and the whole reason for the
# pointer-width change was to make that sentence possible.
#
# WHAT CHANGED. Under wasm32 this block carried a long warning: above 2 GB a pointer exceeds
# INT32_MAX, so any C++ in OCCT, Coin, Qt or CPython that stashed a pointer in a signed int
# would break -- and plausibly as CORRUPT GEOMETRY rather than a clean crash. That hazard is
# gone. Pointers are 64-bit now, and no reachable heap address is near the signed boundary
# of the type holding it. The old ceiling was an architectural limit; the new one is policy.
#
# GROWTH IS ON, which under wasm32 was forbidden here. The old objection was real: growth
# rewrites every direct HEAPU8[...] access into GROWABLE_HEAP_F32()[x>>>2>>>0] accessor form
# and invalidated the hand-derived offsets in tools/patch-freecad-js.py. That objection no
# longer decides anything, because wasm64 changes emscripten codegen regardless -- the patch
# table has to be re-derived for 64-bit indexing either way. Given that, growth is simply the
# right choice: reserving 16 GiB up front would make the module allocate a 16 GiB buffer at
# boot on every machine, most of which do not have it.
#
# THE ONE THING TO VERIFY BEFORE TRUSTING A BIG NUMBER HERE. emscripten had a bug where
# MEMORY64 + pthreads + MAXIMUM_MEMORY above 4 GB failed at link with
#     WebAssembly.Memory(): Property "maximum": value 262144 is above the upper bound 65536
# because the tooling still computed page counts against the 32-bit ceiling
# (emscripten#26311). PR #26357 "Clamp maximum memory if set during run_embind_gen" merged
# 2026-02-27; emsdk 6.0.9 was released 2026-09-01, so the pinned SDK carries it -- verified,
# not assumed. If a link ever dies with that message, the pin moved backwards rather than
# the flag being wrong.
#
#   FCWEB_HEAP_MAX_BYTES=4294967296 bash configure-gui-weh.sh    # 4 GiB, the old ceiling
#
# After changing this, the four checks that matter are unchanged in spirit but now probe a
# different boundary:
#   1. node scratchpad/heapprobe.js       -- pointers past 4 GB behave
#   2. node scratchpad/workflows.js       -- all eight geometry results still exact
#   3. node scratchpad/ccxe2e/run-prod.js -- FEM still matches closed form
#   4. node scratchpad/shot.js            -- render still pixel-identical
# A wrong answer in (2) or (4) with no crash is still the signature of a width bug.
FCWEB_HEAP_MAX_BYTES="${FCWEB_HEAP_MAX_BYTES:-17179869184}"   # 16 GiB
FCWEB_HEAP_FLAGS="-sINITIAL_MEMORY=1073741824 -sMAXIMUM_MEMORY=$FCWEB_HEAP_MAX_BYTES -sALLOW_MEMORY_GROWTH=1"
echo "[heap] initial 1 GiB, ceiling $FCWEB_HEAP_MAX_BYTES bytes, growth ON (wasm64)" >&2
if [ "$FCWEB_HEAP_MAX_BYTES" -gt 17179869184 ]; then
  echo "[heap] WARNING: above 16 GiB. V8 caps wasm64 memory at 16 GiB, so a larger" >&2
  echo "[heap] ceiling cannot be honoured by the browser and the module will fail to" >&2
  echo "[heap] instantiate rather than simply using less." >&2
fi
# ---- Main stack size: deliberately NOT set here --------------------------------------
# This file used to pass -sSTACK_SIZE=32MB in CMAKE_EXE_LINKER_FLAGS. It never took
# effect. Upstream FreeCAD's own cmake appends "-s STACK_SIZE=5MB" to the FreeCADMain
# target AFTER these flags, and emcc takes the last assignment silently, so every green
# build has run a 5 MB main stack while this line claimed 32 MB.
#
# Do not simply add it back: a value stated here loses to upstream, so it buys nothing but
# a false record. To genuinely change the main stack, append it to the END of the link
# line and re-run the gates -- and see the -s STACK_SIZE note in
# scratchpad/linkcmds/fc-linkcmd-weh.sh, which is the command that actually ships.

# numpy C-extension static libs (built by configure-numpy.sh into deps/wasm/lib/numpy-mod).
# Module libs first (provide PyInit_*), then support libs (npymath/mtargets/dispatch/highway).
NPYLIBS=""
if [ -d "$DW/lib/numpy-mod" ]; then
  # Single space-separated line (newlines would become ninja line-continuations
  # WITHOUT spaces, concatenating the paths). Module libs first, then support libs.
  # CPU dispatch: link the AGGREGATES if this numpy built any, otherwise the per-dispatch
  # BASELINE archives. Linking both duplicates the dispatch static initializers and numpy
  # aborts at import with "CPU dispatcher tracer already initlized", which is why baseline
  # used to be excluded unconditionally. But numpy 2.1.3 for wasm builds NO *_mtargets.a at
  # all -- there are no SIMD targets to aggregate -- so excluding baseline removed the only
  # copy and the FreeCAD link ended in
  #     libnpy__multiarray_umath.a(meson-generated_arraytypes.c.o):
  #         undefined symbol: BOOL_argmax        (and BYTE_/INT_/LONG_/... argmax + argmin)
  # Decide from what is on disk, not from what an x86 numpy build happens to produce.
  if ls "$DW"/lib/numpy-mod/*_mtargets.a >/dev/null 2>&1; then
    _npy_skip='libnpy_(_multiarray|_pocketfft|_umath_linalg|lapack_lite)\.a|dispatch\.h_baseline\.a'
    echo "numpy:        dispatch aggregates present -- excluding the baseline archives"
  else
    _npy_skip='libnpy_(_multiarray|_pocketfft|_umath_linalg|lapack_lite)\.a'
    echo "numpy:        no *_mtargets.a -- linking the per-dispatch baseline archives"
  fi
  NPYLIBS="$( { ls "$DW"/lib/numpy-mod/libnpy__multiarray_umath.a "$DW"/lib/numpy-mod/libnpy__pocketfft_umath.a "$DW"/lib/numpy-mod/libnpy__umath_linalg.a "$DW"/lib/numpy-mod/libnpy_lapack_lite.a; ls "$DW"/lib/numpy-mod/*.a | grep -vE "$_npy_skip"; } 2>/dev/null | tr '\n' ' ')"
  echo "numpy:        $(printf '%s' "$NPYLIBS" | wc -w | tr -d ' ') archive(s) on the link line"
fi

# matplotlib C-extension static libs (built by configure-matplotlib-weh.sh into
# deps/wasm/lib/mpl-mod). The libmpl_*.a modules provide PyInit_*; the shared
# libfreetype/libqhull_r/libagg/libttconv resolve their undefined refs once.
# Skip the _tkagg backend (Tk is unavailable and not registered).
MPLLIBS=""
if [ -d "$DW/lib/mpl-mod" ]; then
  MPLLIBS="$(ls "$DW"/lib/mpl-mod/*.a 2>/dev/null | grep -vE 'libmpl__tkagg\.a' | tr '\n' ' ')"
fi
# kiwisolver C extension (matplotlib layout dependency)
if [ -d "$DW/lib/kiwi-mod" ]; then
  MPLLIBS="$MPLLIBS $(ls "$DW"/lib/kiwi-mod/*.a 2>/dev/null | tr '\n' ' ')"
fi
# _ctypes module + libffi (enables ctypes + interactive matplotlib QtAgg canvas)
if [ -d "$DW/lib/ctypes-mod" ]; then
  MPLLIBS="$MPLLIBS $(ls "$DW"/lib/ctypes-mod/*.a 2>/dev/null | tr '\n' ' ') $DW/lib/libffi.a"
fi
# Pillow _imaging (matplotlib image IO)
if [ -d "$DW/lib/pil-mod" ]; then
  MPLLIBS="$MPLLIBS $(ls "$DW"/lib/pil-mod/*.a 2>/dev/null | tr '\n' ' ')"
fi

emcmake cmake -S deps/src/freecad -B build-freecad-gui-weh -G Ninja \
  -DCMAKE_POLICY_VERSION_MINIMUM=3.5 \
  `# Configure-time checks must COMPILE, not LINK. CMAKE_EXE_LINKER_FLAGS below carries the` \
  `# whole production link line -- every archive, --pre-js, the preload list -- and one of` \
  `# its entries is build-freecad-gui-weh/src/Mod/Draft/App/DraftUtils.a, which does not` \
  `# exist until this build has produced it. So every try_compile that links fails, and the` \
  `# first casualty is VTK's find_package(Threads):` \
  `#     Could NOT find Threads (missing: Threads_FOUND)` \
  `#     VTK-vtk-module-find-packages.cmake:162 -> SetupSalomeSMESH.cmake:34` \
  `# On the build machine DraftUtils.a was left over from an earlier build, so the checks` \
  `# linked and passed -- the same uncaptured-state defect as the truncated command above.` \
  -DCMAKE_TRY_COMPILE_TARGET_TYPE=STATIC_LIBRARY \
  `# ...and because that makes any LINK-based probe unreliable, answer the one probe that` \
  `# is REQUIRED outright instead of letting it guess. VTK's config does` \
  `# find_package(Threads REQUIRED) and FindThreads decides via CHECK_SYMBOL_EXISTS, whose` \
  `# result is cached as CMAKE_HAVE_LIBC_PTHREAD -- so once a configure has failed, the` \
  `# NEGATIVE sits in CMakeCache.txt and every later configure against that build tree` \
  `# repeats it. Emscripten has pthreads and this build passes -pthread everywhere, so the` \
  `# answer is known; state it. FindThreads sets Threads_FOUND from these three.` \
  -DCMAKE_HAVE_LIBC_PTHREAD=1 \
  -DTHREADS_PREFER_PTHREAD_FLAG=ON \
  -DCMAKE_THREAD_LIBS_INIT=-pthread \
  -DCMAKE_PROJECT_INCLUDE_BEFORE="$ROOT/force-static.cmake" \
  -DCMAKE_INSTALL_PREFIX="$ROOT/freecad-gui-install" \
  -DFCWEB_DW="$DW" \
  -DCMAKE_BUILD_TYPE=Release \
  -DBUILD_GUI=ON \
  `# ON installs the freecad namespace package into the HOST python's site-packages,`\
  `# which a cross build cannot write and which never reaches the wasm FS. OFF puts it`\
  `# in <prefix>/Ext/freecad, the tree that is preloaded as /freecad/Ext.` \
  -DINSTALL_TO_SITEPACKAGES=OFF \
  -DFREECAD_USE_PYSIDE=OFF -DFREECAD_USE_SHIBOKEN=OFF \
  -DCMAKE_DISABLE_FIND_PACKAGE_Shiboken6=ON -DCMAKE_DISABLE_FIND_PACKAGE_PySide6=ON \
  -DBUILD_FEM=ON -DBUILD_ADDONMGR=ON -DBUILD_BIM=ON -DBUILD_DRAFT=ON \
  -DBUILD_HELP=ON -DBUILD_IDF=ON -DBUILD_IMPORT=ON -DBUILD_INSPECTION=ON \
  -DBUILD_MATERIAL=ON -DBUILD_MESH=ON -DBUILD_MESH_PART=ON -DBUILD_FLAT_MESH=OFF \
  -DENABLE_DEVELOPER_TESTS=OFF \
  -DBUILD_OPENSCAD=ON -DBUILD_SMESH=ON -DBUILD_PART_DESIGN=ON -DBUILD_CAM=ON -DBUILD_ASSEMBLY=ON \
  -DFREECAD_USE_PYBIND11=ON -Dpybind11_DIR="$PYBIND11_DIR" \
  `# FreeCAD 1.1 needs ICU, and CMake 4 removed FindBoost. toolchain/cmake supplies both`   `# (FindICU maps the emscripten port library names; FindBoost handles the b2-staged`   `# layout, which ships no BoostConfig.cmake). FreeCAD only APPENDS to`   `# CMAKE_MODULE_PATH, so this stays ahead of CMake own Modules directory.`   -DCMAKE_MODULE_PATH="$ROOT/toolchain/cmake" \
  -DICU_EM_SYSROOT="$SYSROOT" \
  -DVTK_DIR="$DW/lib/cmake/vtk-9.3" \
  -DBUILD_PLOT=ON -DBUILD_POINTS=ON -DBUILD_REVERSEENGINEERING=ON -DBUILD_ROBOT=ON \
  -DBUILD_SHOW=ON -DBUILD_SKETCHER=ON -DBUILD_SPREADSHEET=ON -DBUILD_START=ON \
  -DBUILD_TEST=ON -DBUILD_MEASURE=ON -DBUILD_TECHDRAW=ON -DBUILD_TUX=ON \
  -DBUILD_WEB=ON -DBUILD_SURFACE=ON -DBUILD_PART=ON \
  -DBUILD_DYNAMIC_LINK_PYTHON=OFF \
  `# SetupCoin3D.cmake otherwise imports pivy in the HOST python to compare its Coin`   `# version against the one being built. That makes the cross-build depend on an`   `# ambient host package -- exactly the uncaptured-state problem this repo keeps`   `# getting bitten by. FreeCAD guards it for this reason; take the guard.`   `# E57_RELEASE_LTO defaults ON, putting INTERPROCEDURAL_OPTIMIZATION on the bundled` \n  `# libE57Format target ALONE. Nothing else here is built with LTO, so it buys nothing,` \n  `# and it makes emscripten build a separate set of port variants under` \n  `# sysroot/lib/wasm64-emscripten/thinlto/, where its ICU port dies with` \n  `#   tools/ports/icu.py:89 ... TypeError: expected str, bytes or os.PathLike, not NoneType` \n  `# check_ipo_supported() answers yes under emscripten, so it never switches itself off.` \n  -DE57_RELEASE_LTO=OFF \n  -DFREECAD_CHECK_PIVY=OFF \
  -DFREECAD_USE_EXTERNAL_PIVY=OFF -DFREECAD_USE_PCH=OFF \
  `# FreeType ON: without it Part.makeWireString() raises "FreeCAD compiled without FreeType` \
  `# support!", which kills Draft ShapeString (text/engraving) entirely. Point it at the` \
  `# freetype matplotlib already builds and that is already on the link line. NOTE: Qt ships` \
  `# its own bundled freetype too, so wasm-ld warns about FT_Request_Metrics /` \
  `# ft_module_get_service signature mismatches between the two copies -- pre-existing, and` \
  `# benign in practice (Qt text and ShapeString both render), but see patches/README.` \
  -DFREECAD_USE_FREETYPE=ON \
  -DFREETYPE_INCLUDE_DIRS="$FT_INC" \
  -DFREETYPE_INCLUDE_DIR_ft2build="$FT_INC" \
  -DFREETYPE_INCLUDE_DIR_freetype2="$FT_INC" \
  -DFREETYPE_LIBRARY="$ROOT/deps/wasm/lib/mpl-mod/libfreetype.a" \
  -DFREETYPE_LIBRARIES="$ROOT/deps/wasm/lib/mpl-mod/libfreetype.a" \
  -DCMAKE_PREFIX_PATH="$DW;$ROOT/qt/6.11.2/wasm_mt_weh" \
  -DCMAKE_FIND_ROOT_PATH="$DW;$ROOT/qt/6.11.2/wasm_mt_weh" \
  -DCMAKE_FIND_ROOT_PATH_MODE_PACKAGE=BOTH \
  -DFREECAD_QT_VERSION=6 \
  -DBoost_USE_STATIC_LIBS=ON -DBoost_USE_STATIC_RUNTIME=ON \
  -DQt6_DIR="$ROOT/qt/6.11.2/wasm_mt_weh/lib/cmake/Qt6" \
  -DQT_HOST_PATH="$QT_HOST" \
  -DOpenCASCADE_DIR="$DW/lib/cmake/opencascade" \
  -DEIGEN3_INCLUDE_DIR="$EIGEN_INC" \
  -DCOIN3D_INCLUDE_DIRS="$DW/include" \
  -DCOIN3D_LIBRARIES="$DW/lib/libCoin.a" \
  -DCOIN3D_FOUND=ON \
  -DPython3_EXECUTABLE="$HOSTPY" \
  -DPython3_INCLUDE_DIR="$PYINC" \
  -DPython3_LIBRARY="$PYMT/libpython3.13.a" \
  -DPYTHON_VERSION_STRING=3.13 \
  `# -DCMAKE_DISABLE_FIND_PACKAGE_OpenMP=ON: src/Mod/Fem/App/CMakeLists.txt does` \
  `# find_package(OpenMP 4.0) and links OpenMP::OpenMP_CXX when found. Under emsdk 6.0.9` \
  `# and cmake 4.2 the probe now succeeds (clang accepts -fopenmp), so FemMesh.cpp's` \
  `# #pragma omp loops compiled to calls into an OpenMP runtime emscripten does not have:` \
  `#     wasm-ld: error: Fem.a(FemMesh.cpp.o): undefined symbol: __kmpc_fork_call` \
  `# Without the package the pragmas are ignored, which is what the wasm32 build had.` \
  -DCMAKE_DISABLE_FIND_PACKAGE_OpenMP=ON \
  -DZLIB_INCLUDE_DIR="$SYSROOT/include" \
  -DZLIB_LIBRARY="$SYSROOT/lib/wasm64-emscripten/libz.a" \
  `# -include cstdlib: LLVM 20 libc++ no longer includes <cstdlib> through <string>, <stdexcept>` \
  `# or <new>, even at -std=c++20, and fmt 11.1.4 -- the release FreeCAD pins by URL+MD5 in` \
  `# SetupLibFmt.cmake -- calls malloc/free bare (fmt #4520). Same mechanism as the two headers` \
  `# below; keep build-freecad.yml in step.` \
  -DCMAKE_CXX_FLAGS="-fwasm-exceptions -pthread -O2 -DBOOST_ALL_NO_LIB --use-port=zlib --use-port=icu -I$DW/include -include cstdlib -include $DW/include/gl_compat.h -include $DW/include/coin_intrusive.h" \
  -DCMAKE_C_FLAGS="-fwasm-exceptions -pthread -O2 --use-port=zlib --use-port=icu -I$DW/include -include $DW/include/gl_compat.h -include $DW/include/coin_intrusive.h" \
  -DCMAKE_EXE_LINKER_FLAGS="$FC_LINK_MODE_FLAGS -O2 -lembind -lidbfs.js -pthread -sSUPPORT_LONGJMP=wasm -sJSPI -sJSPI_EXPORTS=fcweb_run_python -fwasm-exceptions -sALLOW_TABLE_GROWTH -sPTHREAD_POOL_SIZE=16 -sASSERTIONS=0 -sFORCE_FILESYSTEM=1 -sMODULARIZE=1 -sEXPORT_NAME=FreeCAD_entry -sDEFAULT_PTHREAD_STACK_SIZE=16MB $FCWEB_HEAP_FLAGS -sMAX_WEBGL_VERSION=2 -sLEGACY_GL_EMULATION=1 -sGL_UNSAFE_OPTS=0 -sERROR_ON_UNDEFINED_SYMBOLS=0 -sEXPORT_EXCEPTION_HANDLING_HELPERS -sFETCH -sEXPORTED_RUNTIME_METHODS=UTF16ToString,stringToUTF16,UTF8ToString,stringToUTF8,JSEvents,specialHTMLTargets,FS,ENV,callMain,ccall -sEXPORTED_FUNCTIONS=_main,__embind_initialize_bindings,_fcweb_run_python,_malloc,_free -Wl,--allow-multiple-definition -Wl,--wrap=_ZN16QCoreApplication9postEventEP7QObjectP6QEventi -Wl,--wrap=_ZN23QCoreApplicationPrivate16sendPostedEventsEP7QObjectiP11QThreadData -Wl,--wrap=_ZN23QCoreApplicationPrivate13notify_helperEP7QObjectP6QEvent $ROOT/weh-objs/postevent_wrap.o $ROOT/weh-objs/fcweb_export_stub.o $ROOT/weh-objs/spe_sanitize.o $ROOT/weh-objs/gl_legacy_stubs.o $ROOT/weh-objs/fcweb_dlg_module.o $ROOT/weh-objs/fcweb_gmsh_module.o $ROOT/weh-objs/fcweb_ccx_module.o  --pre-js=$ROOT/pre-gui.js --use-port=zlib --use-port=bzip2 --use-port=sqlite3 $PYMT/Modules/_decimal/libmpdec/libmpdec.a $PYMT/Modules/_hacl/libHacl_Hash_SHA2.a $PYMT/Modules/expat/libexpat.a -Wl,--start-group ${FCWEB_PYSIDE_LIBS:-$DW/shiboken6/lib/libshiboken6.cpython-313-wasm64-emscripten.a $ROOT/build-pyside-wasm/libpyside/libpyside6.cpython-313-wasm64-emscripten.a $ROOT/build-pyside-wasm/PySide6/QtCore/QtCore.cpython-313-wasm64-emscripten.a $ROOT/build-pyside-wasm/PySide6/QtGui/QtGui.cpython-313-wasm64-emscripten.a $ROOT/build-pyside-wasm/PySide6/QtWidgets/QtWidgets.cpython-313-wasm64-emscripten.a $ROOT/build-pyside-wasm/PySide6/QtNetwork/QtNetwork.cpython-313-wasm64-emscripten.a $ROOT/build-pyside-wasm/PySide6/QtSvg/QtSvg.cpython-313-wasm64-emscripten.a $ROOT/build-shiboken-wasm/shibokenmodule/CMakeFiles/shibokenmodule.dir/Shiboken/shiboken_module_wrapper.cpp.o $ROOT/build-freecad-gui-weh/src/Mod/Draft/App/DraftUtils.a $ROOT/build-freecad-gui-weh/src/Mod/CAM/libarea/area.a $ROOT/build-freecad-gui-weh/src/Mod/CAM/libarea/libarea-native.a $ROOT/build-freecad-gui-weh/src/Mod/Test/Gui/QtUnitGui.a $DW/lib/pivy-mod/lib_coin.a $IFCLIBS} $NPYLIBS $MPLLIBS -Wl,--end-group"
