#!/bin/bash
set -e
cd "$(dirname "$0")"
. toolchain/env.sh
echo "=== COIN ==="; rm -rf build-coin; ./configure-coin-weh.sh
echo "=== XERCES ==="; rm -rf build-xercesc; ./build-xercesc-weh.sh
echo "=== BOOST ==="; rm -rf deps/src/boost/build-wasm deps/src/boost/stage; ./build-boost-weh.sh
echo "=== YAML-CPP ==="
rm -rf build-yamlcpp
emcmake cmake -S deps/src/yaml-cpp -B build-yamlcpp -G Ninja -DCMAKE_BUILD_TYPE=Release -DYAML_BUILD_SHARED_LIBS=OFF -DYAML_CPP_BUILD_TESTS=OFF -DYAML_CPP_BUILD_TOOLS=OFF -DCMAKE_INSTALL_PREFIX="$DW" -DCMAKE_CXX_FLAGS="-fwasm-exceptions -pthread -O2"
ninja -C build-yamlcpp install
echo "LANE2-ALL-DONE"
