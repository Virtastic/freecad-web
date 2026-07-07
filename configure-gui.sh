#!/bin/bash
# Phase 3: configure FreeCAD WITH GUI (BUILD_GUI=ON) for wasm.
# PySide/Shiboken OFF (don't exist for wasm); Coin3D viewport via bundled Quarter.
set -e
cd "$(dirname "$0")"
. toolchain/env.sh
CPY="$ROOT/deps/src/cpython"
PYMT="$CPY/builddir/emscripten-mt"
HOSTPY="$CPY/builddir/build/python.exe"
SYSROOT="$(em-config CACHE)/sysroot"
: "${FC_LINK_MODE_FLAGS:=-sNODERAWFS=1}"

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

emcmake cmake -S deps/src/freecad -B build-freecad-gui -G Ninja \
  -DCMAKE_POLICY_VERSION_MINIMUM=3.5 \
  -DCMAKE_PROJECT_INCLUDE_BEFORE="$ROOT/force-static.cmake" \
  -DCMAKE_INSTALL_PREFIX="$ROOT/freecad-gui-install" \
  -DFCWEB_DW="$DW" \
  -DCMAKE_BUILD_TYPE=Release \
  -DBUILD_GUI=ON \
  -DFREECAD_USE_PYSIDE=OFF -DFREECAD_USE_SHIBOKEN=OFF \
  -DCMAKE_DISABLE_FIND_PACKAGE_Shiboken6=ON -DCMAKE_DISABLE_FIND_PACKAGE_PySide6=ON \
  -DBUILD_FEM=ON -DBUILD_ADDONMGR=OFF -DBUILD_BIM=ON -DBUILD_DRAFT=ON \
  -DBUILD_HELP=ON -DBUILD_IDF=ON -DBUILD_IMPORT=ON -DBUILD_INSPECTION=ON \
  -DBUILD_MATERIAL=ON -DBUILD_MESH=ON -DBUILD_MESH_PART=ON -DBUILD_FLAT_MESH=OFF \
  -DENABLE_DEVELOPER_TESTS=OFF \
  -DBUILD_OPENSCAD=ON -DBUILD_SMESH=ON -DBUILD_PART_DESIGN=ON -DBUILD_CAM=ON -DBUILD_ASSEMBLY=ON \
  -DFREECAD_USE_PYBIND11=ON -Dpybind11_DIR="$ROOT/.qtvenv/lib/python3.14/site-packages/pybind11/share/cmake/pybind11" \
  -DVTK_DIR="$DW/lib/cmake/vtk-9.3" \
  -DBUILD_PLOT=OFF -DBUILD_POINTS=ON -DBUILD_REVERSEENGINEERING=ON -DBUILD_ROBOT=ON \
  -DBUILD_SHOW=ON -DBUILD_SKETCHER=ON -DBUILD_SPREADSHEET=ON -DBUILD_START=ON \
  -DBUILD_TEST=OFF -DBUILD_MEASURE=ON -DBUILD_TECHDRAW=ON -DBUILD_TUX=ON \
  -DBUILD_WEB=ON -DBUILD_SURFACE=ON -DBUILD_PART=ON \
  -DBUILD_DYNAMIC_LINK_PYTHON=OFF \
  -DFREECAD_USE_EXTERNAL_PIVY=OFF -DFREECAD_USE_PCH=OFF -DFREECAD_USE_FREETYPE=OFF \
  -DCMAKE_PREFIX_PATH="$DW;$ROOT/qt/6.9.0/wasm_multithread" \
  -DCMAKE_FIND_ROOT_PATH="$DW;$ROOT/qt/6.9.0/wasm_multithread" \
  -DCMAKE_FIND_ROOT_PATH_MODE_PACKAGE=BOTH \
  -DFREECAD_QT_VERSION=6 \
  -DBoost_USE_STATIC_LIBS=ON -DBoost_USE_STATIC_RUNTIME=ON \
  -DQt6_DIR="$ROOT/qt/6.9.0/wasm_multithread/lib/cmake/Qt6" \
  -DQT_HOST_PATH="$ROOT/qt/6.9.0/macos" \
  -DOpenCASCADE_DIR="$DW/lib/cmake/opencascade" \
  -DEIGEN3_INCLUDE_DIR="$DW/include" \
  -DCOIN3D_INCLUDE_DIRS="$DW/include" \
  -DCOIN3D_LIBRARIES="$DW/lib/libCoin.a" \
  -DCOIN3D_FOUND=ON \
  -DPython3_EXECUTABLE="$HOSTPY" \
  -DPython3_INCLUDE_DIR="$CPY/Include" \
  -DPython3_LIBRARY="$PYMT/libpython3.13.a" \
  -DPYTHON_VERSION_STRING=3.13 \
  -DZLIB_INCLUDE_DIR="$SYSROOT/include" \
  -DZLIB_LIBRARY="$SYSROOT/lib/wasm32-emscripten/libz.a" \
  -DCMAKE_CXX_FLAGS="-fexceptions -pthread -O2 -DBOOST_ALL_NO_LIB --use-port=zlib -I$DW/include -include $DW/include/gl_compat.h -include $DW/include/coin_intrusive.h" \
  -DCMAKE_C_FLAGS="-fexceptions -pthread -O2 --use-port=zlib -I$DW/include -include $DW/include/gl_compat.h -include $DW/include/coin_intrusive.h" \
  -DCMAKE_EXE_LINKER_FLAGS="$FC_LINK_MODE_FLAGS -O1 -lembind -lidbfs.js -pthread -sALLOW_MEMORY_GROWTH -sPTHREAD_POOL_SIZE=16 -sASSERTIONS=1 -sFORCE_FILESYSTEM=1 -sMODULARIZE=1 -sEXPORT_NAME=FreeCAD_entry -sWASM_BIGINT=1 -sSTACK_SIZE=32MB -sDEFAULT_PTHREAD_STACK_SIZE=16MB -sMAXIMUM_MEMORY=4GB -sINITIAL_MEMORY=1073741824 -sMAX_WEBGL_VERSION=2 -sLEGACY_GL_EMULATION=1 -sGL_UNSAFE_OPTS=0 -sERROR_ON_UNDEFINED_SYMBOLS=0 -g2 -sFETCH -sEXPORTED_RUNTIME_METHODS=UTF16ToString,stringToUTF16,UTF8ToString,stringToUTF8,JSEvents,specialHTMLTargets,FS,ENV,callMain,ccall -sEXPORTED_FUNCTIONS=_main,__embind_initialize_bindings,_fcweb_run_python,_malloc,_free -Wl,--allow-multiple-definition -Wl,--wrap=_ZN16QCoreApplication9postEventEP7QObjectP6QEventi -Wl,--wrap=_ZN23QCoreApplicationPrivate16sendPostedEventsEP7QObjectiP11QThreadData -Wl,--wrap=_ZN23QCoreApplicationPrivate13notify_helperEP7QObjectP6QEvent $ROOT/postevent_wrap.o $ROOT/spe_sanitize.o $ROOT/gl_legacy_stubs.o --pre-js=$ROOT/pre-gui.js --use-port=zlib --use-port=bzip2 --use-port=sqlite3 $PYMT/Modules/_decimal/libmpdec/libmpdec.a $PYMT/Modules/_hacl/libHacl_Hash_SHA2.a $PYMT/Modules/expat/libexpat.a -Wl,--start-group ${FCWEB_PYSIDE_LIBS:-$DW/shiboken6/lib/libshiboken6.abi3.a $ROOT/build-pyside-wasm/libpyside/libpyside6.abi3.a $ROOT/build-pyside-wasm/PySide6/QtCore/QtCore.abi3.a $ROOT/build-pyside-wasm/PySide6/QtGui/QtGui.abi3.a $ROOT/build-pyside-wasm/PySide6/QtWidgets/QtWidgets.abi3.a $ROOT/build-shiboken-wasm/shibokenmodule/CMakeFiles/shibokenmodule.dir/Shiboken/shiboken_module_wrapper.cpp.o $ROOT/build-freecad-gui/src/Mod/Draft/App/DraftUtils.a $ROOT/build-pivy-wasm/interfaces/_coin.a $ROOT/build-ifcopenshell/ifcwrap/lib_ifcopenshell_wrapper.a $ROOT/build-ifcopenshell/ifcgeom/libIfcGeom.a $ROOT/build-ifcopenshell/ifcgeom/kernels/libgeometry_kernel_opencascade.a $ROOT/build-ifcopenshell/ifcgeom/Serialization/libgeometry_serializer.a $ROOT/build-ifcopenshell/serializers/libSerializers.a $ROOT/build-ifcopenshell/ifcparse/libIfcParse.a} $NPYLIBS -Wl,--end-group"
