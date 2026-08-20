#!/bin/bash
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
# installs them to qt-host/6.9.0/gcc_64 on Linux; the build machine has qt/6.9.0/macos.
QT_HOST=""
for d in "$ROOT/qt-host/6.9.0/gcc_64" "$ROOT/qt/6.9.0/macos" "$ROOT/qt/6.9.0/gcc_64" \
         "$ROOT/qt-host/6.9.0/macos"; do
    if [ -x "$d/bin/qmake" ] || [ -x "$d/bin/moc" ]; then QT_HOST="$d"; break; fi
done
[ -n "$QT_HOST" ] || { echo "ERROR: no host Qt found (looked for bin/qmake under qt-host/6.9.0/gcc_64, qt/6.9.0/macos, ...)" >&2; exit 1; }
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

# ---- Heap size -------------------------------------------------------------------------
# Default stays 2 GB. Raising it is a real option now, but it is NOT free, and the failure
# mode is nasty enough to be worth stating before anyone changes the number.
#
# Measured: ~72 KB per simple solid, so 2 GB is roughly 20,000 of them -- fine for parts,
# tight for a large assembly.
#
# Why raising INITIAL_MEMORY is the cheap lever, and ALLOW_MEMORY_GROWTH is not: with growth
# OFF, emscripten keeps direct HEAPU8[...] access. Turning growth ON rewrites 841 heap
# accesses into accessor form (GROWABLE_HEAP_F32()[x>>>2>>>0]), which invalidates the entire
# hand-derived patch table in tools/patch-freecad-js.py -- and the hot path here IS the JS GL
# emulation. See BUILD-WEH.md. So: ask for more, do not ask for growth.
#
# THE HAZARD, and it is why the default has not simply been raised. Above 2 GB a pointer
# exceeds INT32_MAX. Any C++ in OCCT, Coin, Qt or CPython that stores a pointer in a signed
# int, or compares one, breaks -- and plausibly as CORRUPT GEOMETRY rather than a clean
# crash, which is the hardest kind of bug to attribute. Nothing here can prove that absent;
# only a build and the full workflow suite can.
#
#   FCWEB_HEAP_BYTES=3221225472 bash configure-gui-weh.sh    # 3 GB
#
# After linking such a build, before trusting it:
#   1. node scratchpad/heapprobe.js       -- pointers past 2 GB behave
#   2. node scratchpad/workflows.js       -- all eight geometry results still exact
#   3. node scratchpad/ccxe2e/run-prod.js -- FEM still matches closed form
#   4. node scratchpad/shot.js            -- render still pixel-identical
# A wrong answer in (2) or (4) with no crash is exactly what the signed-pointer hazard looks
# like. Keep 2 GB shipped until all four pass.
FCWEB_HEAP_BYTES="${FCWEB_HEAP_BYTES:-2147483648}"
FCWEB_HEAP_FLAGS="-sINITIAL_MEMORY=$FCWEB_HEAP_BYTES"
if [ "$FCWEB_HEAP_BYTES" -gt 2147483648 ]; then
  # wasm32 tops out at 4 GB, and emscripten wants MAXIMUM_MEMORY stated once past 2 GB.
  FCWEB_HEAP_FLAGS="$FCWEB_HEAP_FLAGS -sMAXIMUM_MEMORY=$FCWEB_HEAP_BYTES"
  echo "[heap] $FCWEB_HEAP_BYTES bytes -- ABOVE 2 GB: pointers now exceed INT32_MAX." >&2
  echo "[heap] Run heapprobe/workflows/ccxe2e/shot before trusting this build." >&2
fi

# numpy C-extension static libs (built by configure-numpy.sh into deps/wasm/lib/numpy-mod).
# Module libs first (provide PyInit_*), then support libs (npymath/mtargets/dispatch/highway).
NPYLIBS=""
if [ -d "$DW/lib/numpy-mod" ]; then
  # Single space-separated line (newlines would become ninja line-continuations
  # WITHOUT spaces, concatenating the paths). Module libs first, then support libs.
  # The per-dispatch archives (*.dispatch.h_baseline.a) are ALSO aggregated into
  # the *_mtargets.a archives; linking both duplicates the CPU-dispatch static
  # initializers -> numpy aborts with "CPU dispatcher tracer already initlized".
  # Link only the mtargets (which cover all 18 dispatch objects), not the individuals.
  NPYLIBS="$( { ls "$DW"/lib/numpy-mod/libnpy__multiarray_umath.a "$DW"/lib/numpy-mod/libnpy__pocketfft_umath.a "$DW"/lib/numpy-mod/libnpy__umath_linalg.a "$DW"/lib/numpy-mod/libnpy_lapack_lite.a; ls "$DW"/lib/numpy-mod/*.a | grep -vE 'libnpy_(_multiarray|_pocketfft|_umath_linalg|lapack_lite)\.a|dispatch\.h_baseline\.a'; } 2>/dev/null | tr '\n' ' ')"
fi

# matplotlib C-extension static libs (built by configure-matplotlib.sh into
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
  -DBUILD_FEM=ON -DBUILD_ADDONMGR=OFF -DBUILD_BIM=ON -DBUILD_DRAFT=ON \
  -DBUILD_HELP=ON -DBUILD_IDF=ON -DBUILD_IMPORT=ON -DBUILD_INSPECTION=ON \
  -DBUILD_MATERIAL=ON -DBUILD_MESH=ON -DBUILD_MESH_PART=ON -DBUILD_FLAT_MESH=OFF \
  -DENABLE_DEVELOPER_TESTS=OFF \
  -DBUILD_OPENSCAD=ON -DBUILD_SMESH=ON -DBUILD_PART_DESIGN=ON -DBUILD_CAM=ON -DBUILD_ASSEMBLY=ON \
  -DFREECAD_USE_PYBIND11=ON -Dpybind11_DIR="$PYBIND11_DIR" \
  # FreeCAD 1.1 needs ICU, and CMake 4 removed FindBoost. toolchain/cmake supplies both
  # (FindICU maps the emscripten port library names; FindBoost handles the b2-staged
  # layout, which ships no BoostConfig.cmake). FreeCAD only APPENDS to
  # CMAKE_MODULE_PATH, so this stays ahead of CMake own Modules directory.
  -DCMAKE_MODULE_PATH="$ROOT/toolchain/cmake" \
  -DICU_EM_SYSROOT="$SYSROOT" \
  -DVTK_DIR="$DW/lib/cmake/vtk-9.3" \
  -DBUILD_PLOT=ON -DBUILD_POINTS=ON -DBUILD_REVERSEENGINEERING=ON -DBUILD_ROBOT=ON \
  -DBUILD_SHOW=ON -DBUILD_SKETCHER=ON -DBUILD_SPREADSHEET=ON -DBUILD_START=ON \
  -DBUILD_TEST=ON -DBUILD_MEASURE=ON -DBUILD_TECHDRAW=ON -DBUILD_TUX=ON \
  -DBUILD_WEB=ON -DBUILD_SURFACE=ON -DBUILD_PART=ON \
  -DBUILD_DYNAMIC_LINK_PYTHON=OFF \
  # SetupCoin3D.cmake otherwise imports pivy in the HOST python to compare its Coin
  # version against the one being built. That makes the cross-build depend on an
  # ambient host package -- exactly the uncaptured-state problem this repo keeps
  # getting bitten by. FreeCAD guards it for this reason; take the guard.
  -DFREECAD_CHECK_PIVY=OFF \
  -DFREECAD_USE_EXTERNAL_PIVY=OFF -DFREECAD_USE_PCH=OFF \
  `# FreeType ON: without it Part.makeWireString() raises "FreeCAD compiled without FreeType` \
  `# support!", which kills Draft ShapeString (text/engraving) entirely. Point it at the` \
  `# freetype matplotlib already builds and that is already on the link line. NOTE: Qt ships` \
  `# its own bundled freetype too, so wasm-ld warns about FT_Request_Metrics /` \
  `# ft_module_get_service signature mismatches between the two copies -- pre-existing, and` \
  `# benign in practice (Qt text and ShapeString both render), but see patches/README.` \
  -DFREECAD_USE_FREETYPE=ON \
  -DFREETYPE_INCLUDE_DIRS="$ROOT/deps/src/matplotlib/subprojects/freetype-2.6.1/include" \
  -DFREETYPE_INCLUDE_DIR_ft2build="$ROOT/deps/src/matplotlib/subprojects/freetype-2.6.1/include" \
  -DFREETYPE_INCLUDE_DIR_freetype2="$ROOT/deps/src/matplotlib/subprojects/freetype-2.6.1/include" \
  -DFREETYPE_LIBRARY="$ROOT/deps/wasm/lib/mpl-mod/libfreetype.a" \
  -DFREETYPE_LIBRARIES="$ROOT/deps/wasm/lib/mpl-mod/libfreetype.a" \
  -DCMAKE_PREFIX_PATH="$DW;$ROOT/qt/6.9.0/wasm_mt_weh" \
  -DCMAKE_FIND_ROOT_PATH="$DW;$ROOT/qt/6.9.0/wasm_mt_weh" \
  -DCMAKE_FIND_ROOT_PATH_MODE_PACKAGE=BOTH \
  -DFREECAD_QT_VERSION=6 \
  -DBoost_USE_STATIC_LIBS=ON -DBoost_USE_STATIC_RUNTIME=ON \
  -DQt6_DIR="$ROOT/qt/6.9.0/wasm_mt_weh/lib/cmake/Qt6" \
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
  -DZLIB_INCLUDE_DIR="$SYSROOT/include" \
  -DZLIB_LIBRARY="$SYSROOT/lib/wasm32-emscripten/libz.a" \
  -DCMAKE_CXX_FLAGS="-fwasm-exceptions -pthread -O2 -DBOOST_ALL_NO_LIB --use-port=zlib --use-port=icu -I$DW/include -include $DW/include/gl_compat.h -include $DW/include/coin_intrusive.h" \
  -DCMAKE_C_FLAGS="-fwasm-exceptions -pthread -O2 --use-port=zlib --use-port=icu -I$DW/include -include $DW/include/gl_compat.h -include $DW/include/coin_intrusive.h" \
  -DCMAKE_EXE_LINKER_FLAGS="$FC_LINK_MODE_FLAGS -O2 -lembind -lidbfs.js -pthread -sJSPI -sASYNCIFY_EXPORTS=fcweb_run_python -fwasm-exceptions -sALLOW_TABLE_GROWTH -sPTHREAD_POOL_SIZE=16 -sASSERTIONS=0 -sFORCE_FILESYSTEM=1 -sMODULARIZE=1 -sEXPORT_NAME=FreeCAD_entry -sWASM_BIGINT=1 -sSTACK_SIZE=32MB -sDEFAULT_PTHREAD_STACK_SIZE=16MB $FCWEB_HEAP_FLAGS -sMAX_WEBGL_VERSION=2 -sLEGACY_GL_EMULATION=1 -sGL_UNSAFE_OPTS=0 -sERROR_ON_UNDEFINED_SYMBOLS=0 -sFETCH -sEXPORTED_RUNTIME_METHODS=UTF16ToString,stringToUTF16,UTF8ToString,stringToUTF8,JSEvents,specialHTMLTargets,FS,ENV,callMain,ccall -sEXPORTED_FUNCTIONS=_main,__embind_initialize_bindings,_fcweb_run_python,_malloc,_free -Wl,--allow-multiple-definition -Wl,--wrap=_ZN16QCoreApplication9postEventEP7QObjectP6QEventi -Wl,--wrap=_ZN23QCoreApplicationPrivate16sendPostedEventsEP7QObjectiP11QThreadData -Wl,--wrap=_ZN23QCoreApplicationPrivate13notify_helperEP7QObjectP6QEvent $ROOT/weh-objs/postevent_wrap.o $ROOT/weh-objs/fcweb_export_stub.o $ROOT/weh-objs/spe_sanitize.o $ROOT/weh-objs/gl_legacy_stubs.o $ROOT/weh-objs/fcweb_dlg_module.o $ROOT/weh-objs/fcweb_gmsh_module.o $ROOT/weh-objs/fcweb_ccx_module.o  --pre-js=$ROOT/pre-gui.js --use-port=zlib --use-port=bzip2 --use-port=sqlite3 $PYMT/Modules/_decimal/libmpdec/libmpdec.a $PYMT/Modules/_hacl/libHacl_Hash_SHA2.a $PYMT/Modules/expat/libexpat.a -Wl,--start-group ${FCWEB_PYSIDE_LIBS:-$DW/shiboken6/lib/libshiboken6.abi3.a $ROOT/build-pyside-wasm/libpyside/libpyside6.abi3.a $ROOT/build-pyside-wasm/PySide6/QtCore/QtCore.abi3.a $ROOT/build-pyside-wasm/PySide6/QtGui/QtGui.abi3.a $ROOT/build-pyside-wasm/PySide6/QtWidgets/QtWidgets.abi3.a $ROOT/build-shiboken-wasm/shibokenmodule/CMakeFiles/shibokenmodule.dir/Shiboken/shiboken_module_wrapper.cpp.o $ROOT/build-freecad-gui-weh/src/Mod/Draft/App/DraftUtils.a $ROOT/build-pivy-wasm/interfaces/_coin.a $ROOT/build-ifcopenshell/ifcwrap/lib_ifcopenshell_wrapper.a $ROOT/build-ifcopenshell/ifcgeom/libIfcGeom.a $ROOT/build-ifcopenshell/ifcgeom/kernels/libgeometry_kernel_opencascade.a $ROOT/build-ifcopenshell/ifcgeom/Serialization/libgeometry_serializer.a $ROOT/build-ifcopenshell/serializers/libSerializers.a $ROOT/build-ifcopenshell/ifcparse/libIfcParse.a} $NPYLIBS $MPLLIBS -Wl,--end-group"
