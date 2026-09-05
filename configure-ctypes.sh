#!/bin/bash
# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) Virtastic
# Build libffi + CPython _ctypes for wasm64.
# Enables the `ctypes` stdlib module (and thus matplotlib's interactive QtAgg
# canvas). libffi creates function-table entries at runtime for closures, so the
# final FreeCAD link needs -sALLOW_TABLE_GROWTH (added in configure-gui-weh.sh),
# and its JS calls _malloc/_free, so the link must export them (it does).
#
# Source: the upstream libffi 3.8.0 release. Upstream merged the Emscripten port
# and then added a wasm64 target ("Emscripten: Add wasm64 target", #927):
# src/wasm/ffi.c switches on __SIZEOF_POINTER__, recomputes every struct offset
# for 8-byte pointers, and DEC_PTR/ENC_PTR every pointer that crosses the EM_JS
# boundary -- where wasm64 hands JS a BigInt. The hoodmane/libffi-emscripten
# fork this script used to clone never got any of that: its ffi.c is
# HEAPU32[(addr >> 2)] and CHECK_FIELD_OFFSET(ffi_cif, arg_types, 4*2)
# throughout, and its configure.host has no wasm64 case at all:
#     configure: error: "libffi has not been ported to wasm64-unknown-emscripten."
#
# A release tarball also ships a generated configure, so the libtoolize/autogen
# dance -- and the LT_SYS_SYMBOL_USCORE macro this script used to supply because
# the runner's libtool does not define it -- went with the fork.
set -e
cd "$(dirname "$0")"
ROOT="$PWD"; DW="$ROOT/deps/wasm"
source "$ROOT/toolchain/env.sh"

FFI_VERSION=3.8.0
FFI_SHA256=7da3e2d9a171eb0a038f592ecad3ff2bb2550f3496d87b3b29ad0cf4430c0db4
FFI_URL="https://github.com/libffi/libffi/releases/download/v$FFI_VERSION/libffi-$FFI_VERSION.tar.gz"
STAMP="deps/src/libffi/.fcweb-libffi-$FFI_VERSION"

# 1. libffi
# A tree without the stamp is the fork, another version, or half of an extract:
# not this source. Replace it rather than build whatever happens to be there.
if [ ! -f "$STAMP" ]; then
  rm -rf deps/src/libffi
  mkdir -p deps/src/libffi
  curl -fL --retry 3 -o "deps/src/libffi-$FFI_VERSION.tar.gz" "$FFI_URL"
  echo "$FFI_SHA256  deps/src/libffi-$FFI_VERSION.tar.gz" | sha256sum -c -
  tar xzf "deps/src/libffi-$FFI_VERSION.tar.gz" --strip-components=1 -C deps/src/libffi
  rm -f "deps/src/libffi-$FFI_VERSION.tar.gz"
  # Upstream's EM_JS_DEPS omits the helper DEC_PTR expands to at wasm64; whether
  # it is defined at runtime then depends on what else the link happened to pull
  # in. Zero fuzz, fail closed -- the patch says the rest.
  patch -p1 -d deps/src/libffi --dry-run -F0 < patches/libffi-wasm64-em-js-deps.patch
  patch -p1 -d deps/src/libffi -F0 < patches/libffi-wasm64-em-js-deps.patch
  touch "$STAMP"
fi
cd deps/src/libffi
emconfigure ./configure --host=wasm64-unknown-emscripten --enable-static --disable-shared \
  --disable-dependency-tracking CFLAGS="-fPIC -O2 -fwasm-exceptions -sSUPPORT_LONGJMP=wasm -pthread"
emmake make -j4 libffi.la   # 'make' fails on docs (texinfo); build just the lib
FFI="$PWD/wasm64-unknown-emscripten"
# These directories exist on the build machine because the whole stack was built
# there; in a job that only builds the Python extensions they may not.
mkdir -p "$DW/lib" "$DW/include"
cp "$FFI/.libs/libffi.a" "$DW/lib/libffi.a"
cp "$FFI/include/ffi.h" "$FFI/include/ffitarget.h" "$DW/include/"
cd "$ROOT"

# 2. CPython _ctypes module against libffi
CT="$ROOT/deps/src/cpython/Modules/_ctypes"
OUT=/tmp/ctbuild; mkdir -p "$OUT"; rm -f "$OUT"/*.o
FLAGS=(-c -O2 -fwasm-exceptions -sSUPPORT_LONGJMP=wasm -pthread -fPIC
  -DHAVE_FFI_PREP_CIF_VAR -DHAVE_FFI_PREP_CLOSURE_LOC -DHAVE_FFI_CLOSURE_ALLOC -DPy_BUILD_CORE_MODULE
  -I"$DW/include" -I"$ROOT/deps/src/cpython/Include" -I"$ROOT/deps/src/cpython/builddir/emscripten-mt"
  -I"$ROOT/deps/src/cpython/Include/internal" -I"$CT")
# Compile whatever _ctypes actually ships rather than a fixed list: CPython moves these
# between releases (3.13 has no stgdict.c), and a name that no longer exists makes emcc
# fail with "no input files" -- a message that says nothing about which file is missing.
# _ctypes_test.c is the test extension and must not be linked into the module.
shopt -s nullglob
CT_SRCS=()
for f in "$CT"/*.c; do
  case "$(basename "$f")" in
    _ctypes_test.c) continue ;;
  esac
  CT_SRCS+=("$f")
done
shopt -u nullglob
[ "${#CT_SRCS[@]}" -gt 0 ] || { echo "!! no .c sources under $CT"; exit 1; }
echo "_ctypes sources: $(printf '%s ' "${CT_SRCS[@]##*/}")"
for f in "${CT_SRCS[@]}"; do
  emcc "${FLAGS[@]}" "$f" -o "$OUT/$(basename "$f" .c).o"
done
mkdir -p "$DW/lib/ctypes-mod"
"$ROOT/emsdk/upstream/emscripten/emar" rcs "$DW/lib/ctypes-mod/lib_ctypes.a" "$OUT"/*.o
echo "_ctypes built (PyInit__ctypes):"
"$ROOT/emsdk/upstream/emscripten/emnm" "$DW/lib/ctypes-mod/lib_ctypes.a" | grep 'T PyInit'

# Staging version. The lane skips on the archive existing, which cannot tell these
# apart -- hence the marker.
#   1: built -fexceptions (JS exception handling) while every other object in the
#      FreeCAD link is -fwasm-exceptions; the link ended in
#          undefined symbol: __cxa_find_matching_catch_2 / __resumeException /
#          llvm_eh_typeid_for
#   2: -fwasm-exceptions -sSUPPORT_LONGJMP=wasm, against the hoodmane fork.
#   3: the same flags against upstream libffi 3.8.0, the first libffi with a
#      wasm64 target. A v2 archive on a wasm64 runner is the fork's 32-bit ffi.c
#      and never actually built; nothing that old may satisfy the lane.
echo 3 > "$DW/lib/ctypes-mod/.staged"
