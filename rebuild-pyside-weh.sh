#!/bin/bash
set -e
cd "$(dirname "$0")"
. toolchain/env.sh
QNEW="$ROOT/qt/6.9.0/wasm_mt_weh"
TC="$ROOT/emsdk/upstream/emscripten/cmake/Modules/Platform/Emscripten.cmake"
NODE="$ROOT/emsdk/node/22.16.0_64bit/bin/node"
CPY="$ROOT/deps/src/cpython"

echo "=== SHIBOKEN (lib) ==="
rm -rf build-shiboken-wasm
cmake -S deps/src/pyside-setup/sources/shiboken6 -B build-shiboken-wasm -G Ninja \
  -DCMAKE_TOOLCHAIN_FILE="$TC" -DCMAKE_CROSSCOMPILING_EMULATOR="$NODE" \
  -DCMAKE_POLICY_VERSION_MINIMUM=3.5 -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_PROJECT_INCLUDE_BEFORE="$ROOT/force-static.cmake" \
  -DCMAKE_PREFIX_PATH="$QNEW;$ROOT/deps/host/shiboken6" \
  -DCMAKE_FIND_ROOT_PATH="$QNEW;$ROOT/deps/host/shiboken6" \
  -DCMAKE_FIND_ROOT_PATH_MODE_PACKAGE=BOTH \
  -DQt6_DIR="$QNEW/lib/cmake/Qt6" -DQT_HOST_PATH="$ROOT/qt/6.9.0/macos" \
  -DQFP_PYTHON_HOST_PATH=/usr/bin/python3 -DQFP_SHIBOKEN_HOST_PATH="$ROOT/deps/host/shiboken6" \
  -DShiboken_SKIP_GENERATOR_BUILD=ON \
  -DPython_EXECUTABLE="$CPY/builddir/build/python.exe" -DPython_INCLUDE_DIR="$CPY/Include" \
  -DPython_LIBRARY="$CPY/builddir/emscripten-mt/libpython3.13.a" -DPython_SOABI=cpython-313-wasm32-emscripten \
  -DCMAKE_INSTALL_PREFIX="$ROOT/deps/wasm/shiboken6" \
  -DCMAKE_CXX_FLAGS="-pthread -fwasm-exceptions"
ninja -C build-shiboken-wasm install

echo "=== PYSIDE ==="
rm -rf build-pyside-wasm
cmake -S deps/src/pyside-setup/sources/pyside6 -B build-pyside-wasm -G Ninja \
  -DCMAKE_TOOLCHAIN_FILE="$TC" -DCMAKE_CROSSCOMPILING_EMULATOR="$NODE" \
  -DCMAKE_POLICY_VERSION_MINIMUM=3.5 -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_PROJECT_INCLUDE_BEFORE="$ROOT/force-static.cmake" \
  -DCMAKE_PREFIX_PATH="$QNEW;$ROOT/deps/wasm/shiboken6;$ROOT/deps/host/shiboken6" \
  -DCMAKE_FIND_ROOT_PATH="$QNEW;$ROOT/deps/wasm/shiboken6;$ROOT/deps/host/shiboken6" \
  -DCMAKE_FIND_ROOT_PATH_MODE_PACKAGE=BOTH \
  -DQt6_DIR="$QNEW/lib/cmake/Qt6" -DQT_HOST_PATH="$ROOT/qt/6.9.0/macos" \
  -DQFP_PYTHON_HOST_PATH=/usr/bin/python3 -DQFP_SHIBOKEN_HOST_PATH="$ROOT/deps/host/shiboken6" \
  -DShiboken6_DIR="$ROOT/deps/wasm/shiboken6/lib/cmake/Shiboken6" \
  -DMODULES="Core;Gui;Widgets" -DFORCE_LIMITED_API=no \
  -DPython_EXECUTABLE="$CPY/builddir/build/python.exe" -DPython_INCLUDE_DIR="$CPY/Include" \
  -DPython_LIBRARY="$CPY/builddir/emscripten-mt/libpython3.13.a" -DPython_SOABI=cpython-313-wasm32-emscripten \
  -DCMAKE_INSTALL_PREFIX="$ROOT/emsdk/upstream/emscripten/cache/sysroot" \
  -DCMAKE_CXX_FLAGS="-pthread -fwasm-exceptions"
ninja -C build-pyside-wasm

echo "=== PIVY ==="
PIVYFLAGS="-pthread -fwasm-exceptions -O2 -include $DW/include/gl_compat.h"
cmake -B build-pivy-wasm -DCMAKE_CXX_FLAGS="$PIVYFLAGS" .  > /dev/null 2>&1 || true
cmake -S deps/src/pivy -B build-pivy-wasm -DCMAKE_CXX_FLAGS="$PIVYFLAGS"
ninja -C build-pivy-wasm
echo "PYSIDE-LANE-ALL-DONE"
