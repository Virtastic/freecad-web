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

emcmake cmake -S deps/src/freecad -B build-freecad-gui -G Ninja \
  -DCMAKE_POLICY_VERSION_MINIMUM=3.5 \
  -DCMAKE_PROJECT_INCLUDE_BEFORE="$ROOT/force-static.cmake" \
  -DCMAKE_INSTALL_PREFIX="$ROOT/freecad-gui-install" \
  -DFCWEB_DW="$DW" \
  -DCMAKE_BUILD_TYPE=Release \
  -DBUILD_GUI=ON \
  -DFREECAD_USE_PYSIDE=OFF -DFREECAD_USE_SHIBOKEN=OFF \
  -DCMAKE_DISABLE_FIND_PACKAGE_Shiboken6=ON -DCMAKE_DISABLE_FIND_PACKAGE_PySide6=ON \
  -DBUILD_FEM=OFF -DBUILD_ADDONMGR=OFF -DBUILD_BIM=OFF -DBUILD_DRAFT=ON \
  -DBUILD_HELP=OFF -DBUILD_IDF=OFF -DBUILD_IMPORT=OFF -DBUILD_INSPECTION=OFF \
  -DBUILD_MATERIAL=ON -DBUILD_MESH=OFF -DBUILD_MESH_PART=OFF -DBUILD_FLAT_MESH=OFF \
  -DENABLE_DEVELOPER_TESTS=OFF \
  -DBUILD_OPENSCAD=OFF -DBUILD_PART_DESIGN=ON -DBUILD_CAM=OFF -DBUILD_ASSEMBLY=OFF \
  -DBUILD_PLOT=OFF -DBUILD_POINTS=OFF -DBUILD_REVERSEENGINEERING=OFF -DBUILD_ROBOT=OFF \
  -DBUILD_SHOW=OFF -DBUILD_SKETCHER=ON -DBUILD_SPREADSHEET=ON -DBUILD_START=OFF \
  -DBUILD_TEST=OFF -DBUILD_MEASURE=OFF -DBUILD_TECHDRAW=OFF -DBUILD_TUX=OFF \
  -DBUILD_WEB=OFF -DBUILD_SURFACE=OFF -DBUILD_PART=ON \
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
  -DCMAKE_CXX_FLAGS="-fexceptions -pthread -O2 -DBOOST_ALL_NO_LIB --use-port=zlib -include $DW/include/gl_compat.h -include $DW/include/coin_intrusive.h" \
  -DCMAKE_C_FLAGS="-fexceptions -pthread -O2 --use-port=zlib -include $DW/include/gl_compat.h -include $DW/include/coin_intrusive.h" \
  -DCMAKE_EXE_LINKER_FLAGS="$FC_LINK_MODE_FLAGS -O1 -lembind -pthread -sALLOW_MEMORY_GROWTH -sPTHREAD_POOL_SIZE=16 -sASSERTIONS=1 -sFORCE_FILESYSTEM=1 -sMODULARIZE=1 -sEXPORT_NAME=FreeCAD_entry -sWASM_BIGINT=1 -sSTACK_SIZE=32MB -sDEFAULT_PTHREAD_STACK_SIZE=16MB -sMAXIMUM_MEMORY=4GB -sINITIAL_MEMORY=1073741824 -sMAX_WEBGL_VERSION=2 -sLEGACY_GL_EMULATION=1 -sGL_UNSAFE_OPTS=0 -sERROR_ON_UNDEFINED_SYMBOLS=0 -g2 -sFETCH -sEXPORTED_RUNTIME_METHODS=UTF16ToString,stringToUTF16,UTF8ToString,stringToUTF8,JSEvents,specialHTMLTargets,FS,ENV,callMain,ccall -sEXPORTED_FUNCTIONS=_main,__embind_initialize_bindings,_fcweb_run_python,_malloc,_free -Wl,--allow-multiple-definition -Wl,--wrap=_ZN16QCoreApplication9postEventEP7QObjectP6QEventi -Wl,--wrap=_ZN23QCoreApplicationPrivate16sendPostedEventsEP7QObjectiP11QThreadData -Wl,--wrap=_ZN23QCoreApplicationPrivate13notify_helperEP7QObjectP6QEvent $ROOT/postevent_wrap.o $ROOT/spe_sanitize.o $ROOT/gl_legacy_stubs.o --pre-js=$ROOT/pre-gui.js --use-port=zlib --use-port=bzip2 --use-port=sqlite3 $PYMT/Modules/_decimal/libmpdec/libmpdec.a $PYMT/Modules/_hacl/libHacl_Hash_SHA2.a $PYMT/Modules/expat/libexpat.a -Wl,--start-group ${FCWEB_PYSIDE_LIBS:-$DW/shiboken6/lib/libshiboken6.abi3.a $ROOT/build-pyside-wasm/libpyside/libpyside6.abi3.a $ROOT/build-pyside-wasm/PySide6/QtCore/QtCore.abi3.a $ROOT/build-pyside-wasm/PySide6/QtGui/QtGui.abi3.a $ROOT/build-pyside-wasm/PySide6/QtWidgets/QtWidgets.abi3.a $ROOT/build-shiboken-wasm/shibokenmodule/CMakeFiles/shibokenmodule.dir/Shiboken/shiboken_module_wrapper.cpp.o $ROOT/build-freecad-gui/src/Mod/Draft/App/DraftUtils.a $ROOT/build-pivy-wasm/interfaces/_coin.a} -Wl,--end-group"
