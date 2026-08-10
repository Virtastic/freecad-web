#!/usr/bin/env bash
# Build SPOOLES 2.2 (CalculiX's direct sparse solver) as a wasm static library.
#
# SPOOLES ships a per-directory makeLib system that shells out to sh/awk and hardcodes
# `cc`. Rather than port 46 makefiles, this just compiles every */src/*.c -- that set IS
# the library; everything else in the tree is drivers and self-tests.
#
# The find pattern is anchored at $SRC on purpose: the repo path itself contains
# a /src/ component, so an unanchored '*/src/*.c' sweeps in every driver too.
#
# MPI/ and MT/ are excluded: they need an MPI implementation and SPOOLES' own pthread
# layer, and ccx's serial path (the one we link) uses neither.
#
# The code is from 1999 and predates C99, so the modern-clang errors that would otherwise
# stop the build are demoted -- see the -Wno- list. Output: deps/wasm/lib/libspooles.a
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
source "$ROOT/emsdk/emsdk_env.sh" >/dev/null 2>&1
SRC="$ROOT/deps/src/spooles/SPOOLES.2.2"
PREFIX="$ROOT/deps/wasm"
OBJ="$ROOT/build-spooles-weh"

test -d "$SRC" || { echo "missing $SRC -- extract spooles.2.2.tgz first" >&2; exit 1; }
rm -rf "$OBJ"; mkdir -p "$OBJ" "$PREFIX/lib"

CFLAGS="-fwasm-exceptions -O2 -I$SRC -DARCH=Linux
  -Wno-implicit-function-declaration -Wno-implicit-int -Wno-int-conversion
  -Wno-return-type -Wno-parentheses -Wno-format -Wno-deprecated-non-prototype"

n=0
while IFS= read -r f; do
  rel="${f#$SRC/}"
  out="$OBJ/$(echo "${rel%.c}" | tr '/' '_').o"
  emcc $CFLAGS -c "$f" -o "$out" 2>>"$OBJ/warnings.log" || { echo "FAILED: $rel" >&2; exit 1; }
  n=$((n+1))
done < <(find "$SRC" -path "$SRC/*/src/*.c" ! -path "$SRC/MPI/*" ! -path "$SRC/MT/*" | sort)

emar rcs "$PREFIX/lib/libspooles.a" "$OBJ"/*.o
echo "compiled $n objects -> $PREFIX/lib/libspooles.a"
ls -la "$PREFIX/lib/libspooles.a"
