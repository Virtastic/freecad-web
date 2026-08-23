#!/bin/bash
# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) Virtastic
# Spike (c): link embed.cpp against our wasm libpython3.13.a and run in node.
set -e
cd "$(dirname "$0")"
. ../../toolchain/env.sh
CPY="$ROOT/deps/src/cpython"
EM="$CPY/builddir/emscripten"

# NOTE: the cpython emscripten node build is single-threaded (no -pthread/atomics),
# so we must link WITHOUT -pthread. _decimal needs the bundled libmpdec.
em++ embed.cpp -O2 -fexceptions \
  -I"$CPY/Include" -I"$CPY" -I"$EM" \
  "$EM/libpython3.13.a" \
  "$EM/Modules/_decimal/libmpdec/libmpdec.a" \
  "$EM/Modules/_hacl/libHacl_Hash_SHA2.a" \
  "$EM/Modules/expat/libexpat.a" \
  --use-port=zlib --use-port=bzip2 --use-port=sqlite3 \
  -sALLOW_MEMORY_GROWTH=1 -sEXIT_RUNTIME=1 -sNODERAWFS=1 \
  -sSTACK_SIZE=4MB \
  -o "$EM/embed.js"

echo "=== running spike (c) in node (from build dir, like python.js) ==="
# Run co-located with CPython's build markers so getpath finds the in-tree stdlib,
# exactly as the build's own python.js does.
cd "$EM" && FCWEB_PYLIB="$CPY/Lib" node embed.js
