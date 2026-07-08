#!/bin/bash
# Cross-compile Pillow 10.4.0 PIL._imaging to wasm (matplotlib image I/O + PNG).
# PNG uses Pillow's zlib-based codec (no libpng needed); JPEG/TIFF/WebP/LCMS/
# FreeType-text extensions are omitted (not needed by matplotlib's Agg PNG path).
set -e
cd "$(dirname "$0")"
ROOT="$PWD"; DW="$ROOT/deps/wasm"; P="$ROOT/deps/src/Pillow"
source emsdk/emsdk_env.sh >/dev/null 2>&1
OUT=/tmp/pilbuild; mkdir -p "$OUT"; rm -f "$OUT"/*.o
FLAGS=(-c -O2 -fexceptions -pthread -fPIC -DHAVE_LIBZ -DPILLOW_VERSION='"10.4.0"' --use-port=zlib
  -I"$P/src/libImaging" -I"$ROOT/deps/src/cpython/Include" -I"$ROOT/deps/src/cpython/builddir/emscripten-mt")
SRCS=("$P"/src/_imaging.c "$P"/src/decode.c "$P"/src/encode.c "$P"/src/map.c
      "$P"/src/display.c "$P"/src/outline.c "$P"/src/path.c "$P"/src/libImaging/*.c)
for s in "${SRCS[@]}"; do emcc "${FLAGS[@]}" "$s" -o "$OUT/$(basename "$s" .c).o"; done
mkdir -p "$DW/lib/pil-mod"
"$ROOT/emsdk/upstream/emscripten/emar" rcs "$DW/lib/pil-mod/libpil__imaging.a" "$OUT"/*.o
echo "Pillow _imaging built (PyInit__imaging):"
"$ROOT/emsdk/upstream/emscripten/emnm" "$DW/lib/pil-mod/libpil__imaging.a" | grep 'T PyInit'
