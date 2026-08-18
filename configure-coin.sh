#!/bin/bash
# Coin3D static cross-compile for wasm32-emscripten (the older -fexceptions lane; the shipped
# build uses configure-coin-weh.sh). GLES/WebGL2 target, force-include the
# reused gl_compat.h shim.
#
# THIS SCRIPT USED TO CONFIGURE AND NOTHING ELSE, AND COULD NOT REPORT FAILURE.
#
# It began life as spike (e) -- "can Coin3D even configure under emscripten?" -- and was
# never promoted, but BUILD-WEH.md lists it as the Coin3D build step and configure-gui-weh.sh
# links $DW/lib/libCoin.a. Nothing in the repository ever built that library.
#
# It also ended in `2>&1 | tail -25`, so the pipeline's status was tail's, always 0. `set -e`
# cannot see through that. CI run 32077362742 duly reported `coin exit=0 in 3s` while cmake
# had died on "Could NOT find Boost (missing: Boost_INCLUDE_DIR)" -- a step that produced no
# library, took three seconds, and was recorded as a success.
#
# Three fixes, one per defect: build and install; let the status escape; hand FindBoost the
# include directory as a CACHE variable, because emscripten's toolchain file sets
# CMAKE_FIND_ROOT_PATH_MODE_INCLUDE=ONLY -- which confines find_path to the sysroot and is
# why exporting BOOST_ROOT in the environment did not help.
set -e
cd "$(dirname "$0")"
. toolchain/env.sh

# gl_compat.h is force-included below; fail here, by name, rather than in Coin's first
# translation unit.
bash toolchain/stage-headers.sh

# Coin wants Boost headers only (CMakeLists.txt:178). Point straight at them.
BOOST_INC="${FCWEB_BOOST_INCLUDE_DIR:-$DW/include}"
[ -e "$BOOST_INC/boost/version.hpp" ] || {
  echo "ERROR: no boost/version.hpp under $BOOST_INC -- run build-boost-weh.sh first." >&2
  exit 1
}

emcmake cmake -S deps/src/coin3d -B build-coin -G Ninja \
  -DCMAKE_POLICY_VERSION_MINIMUM=3.5 \
  -DCMAKE_POLICY_DEFAULT_CMP0167=OLD \
  -DBoost_INCLUDE_DIR="$BOOST_INC" \
  -DBoost_NO_BOOST_CMAKE=ON \
  -DCMAKE_BUILD_TYPE=Release \
  -DBUILD_SHARED_LIBS=OFF \
  -DCOIN_BUILD_SHARED_LIBS=OFF \
  -DCOIN_BUILD_TESTS=OFF \
  -DCOIN_BUILD_DOCUMENTATION=OFF \
  -DCOIN_BUILD_GLX=OFF \
  -DCOIN_BUILD_EGL=OFF \
  -DCMAKE_DISABLE_FIND_PACKAGE_X11=ON \
  -DCMAKE_INSTALL_PREFIX="$DW" \
  -DCMAKE_CXX_FLAGS="-fexceptions -pthread -O2 -DGLES_SILENCE_DEPRECATION -include $DW/include/gl_compat.h" \
  -DCMAKE_C_FLAGS="-fexceptions -pthread -O2 -include $DW/include/gl_compat.h" \
  -DOPENGL_INCLUDE_DIR="$(em-config CACHE)/sysroot/include" \
  -DOPENGL_gl_LIBRARY="GL"

echo "=== Coin3D configure done; building ==="
ninja -C build-coin
ninja -C build-coin install

# An install that puts nothing where the FreeCAD link expects it is a failed build, however
# cleanly ninja exited. configure-gui-weh.sh names this exact path.
if [ ! -s "$DW/lib/libCoin.a" ]; then
  echo "ERROR: ninja install succeeded but $DW/lib/libCoin.a is missing or empty." >&2
  ls -la "$DW/lib" 2>/dev/null | head -20 >&2
  exit 1
fi

echo "=== Coin3D build+install complete ==="
ls -la "$DW/lib/libCoin.a"
