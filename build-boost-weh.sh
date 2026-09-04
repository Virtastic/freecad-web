#!/bin/bash
# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) Virtastic
# Build the Boost libs FreeCAD core needs, static, for wasm64-emscripten (-pthread).
set -e
cd "$(dirname "$0")"
. toolchain/env.sh
BSRC="$ROOT/deps/src/boost"
cd "$BSRC"

# Host b2 (bootstrap once).
if [ ! -x ./b2 ]; then ./bootstrap.sh; fi

# Custom emscripten toolset.
cat > user-config.jam <<'EOF'
using clang : emscripten : em++ :
  <archiver>emar
  <ranlib>emranlib
  <cxxflags>"-fwasm-exceptions -pthread -O2 -Wno-unused-command-line-argument"
  <linkflags>"-fwasm-exceptions -pthread" ;
EOF

./b2 -j8 --user-config=user-config.jam \
  toolset=clang-emscripten \
  link=static runtime-link=static threading=multi \
  target-os=linux \
  --with-filesystem --with-program_options --with-regex \
  --with-system --with-thread --with-date_time \
  --stagedir="$BSRC/stage" --build-dir="$BSRC/build-wasm" \
  stage

echo "=== boost stage libs ==="
ls -la "$BSRC/stage/lib/"*.a 2>/dev/null
# Install into the dep prefix.
mkdir -p "$DW/lib" "$DW/include"
cp "$BSRC/stage/lib/"*.a "$DW/lib/" 2>/dev/null || true
# Headers (header-only parts + the built libs' headers).
rsync -a --delete "$BSRC/boost" "$DW/include/" 2>/dev/null || cp -R "$BSRC/boost" "$DW/include/"
echo "=== installed boost libs ===" && ls "$DW/lib/"libboost_*.a 2>/dev/null
