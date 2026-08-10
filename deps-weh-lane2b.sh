#!/bin/bash
set -e
cd "$(dirname "$0")"
. toolchain/env.sh
echo "=== COIN BUILD ==="
ninja -C build-coin install
echo "=== YAML-CPP ==="
rm -rf build-yamlcpp
emcmake cmake -S deps/src/yaml-cpp -B build-yamlcpp -G Ninja -DCMAKE_POLICY_VERSION_MINIMUM=3.5 -DCMAKE_BUILD_TYPE=Release -DYAML_BUILD_SHARED_LIBS=OFF -DYAML_CPP_BUILD_TESTS=OFF -DYAML_CPP_BUILD_TOOLS=OFF -DCMAKE_INSTALL_PREFIX="$DW" -DCMAKE_CXX_FLAGS="-fwasm-exceptions -pthread -O2"
ninja -C build-yamlcpp install
echo "LANE2B-ALL-DONE"
