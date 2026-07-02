#!/bin/bash
# Single source of truth for the FreeCAD-Web wasm toolchain.
# Usage:  . toolchain/env.sh   (source it; do NOT execute)
#
# Pins emscripten to 3.1.74 (targets Qt 6.9). Every build/spike script must
# source this first so nothing accidentally falls back to Homebrew emscripten.

export ROOT=/Users/mstavridis/Downloads/FreeCAD-Web

# Bring emcc/em++/emcmake/node/python onto PATH from the pinned SDK.
source "$ROOT/emsdk/emsdk_env.sh" >/dev/null 2>&1

# Cross-compiled dependency prefix: .a -> $DW/lib, headers -> $DW/include.
export DW="$ROOT/deps/wasm"

# Sanity echo so a wrong toolchain is obvious immediately.
echo "[env] emcc: $(emcc --version 2>/dev/null | head -1)"
echo "[env] which emcc: $(command -v emcc)"
echo "[env] DW=$DW"
