#!/usr/bin/env bash
# Build libf2c (the runtime that f2c-translated Fortran calls into) as a wasm library.
#
# Needed because CalculiX is Fortran and emscripten has no Fortran frontend: tools/f77ify.py
# rewrites the F90, f2c translates to C, and every translated file calls into this.
#
# Two deviations from libf2c's own makefile:
#   - arithchk.c generates arith.h by RUNNING a probe binary. That cannot work when the
#     host and target differ, so the probe is compiled and run natively.
#   - emscripten provides a POSIX stdio, so the default (Unix) fseek/ftell path is used.
#   - main.c/getarg_/iargc_ are dropped: ccx supplies its own main, and this is linked
#     into a module that is called, not executed.
# Output: deps/wasm/lib/libf2c.a
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
source "$ROOT/emsdk/emsdk_env.sh" >/dev/null 2>&1
SRC="$ROOT/deps/src/f2c/libf2c"
PREFIX="$ROOT/deps/wasm"
OBJ="$ROOT/build-libf2c-weh"

test -d "$SRC" || { echo "missing $SRC" >&2; exit 1; }
rm -rf "$OBJ"; mkdir -p "$OBJ" "$PREFIX/lib" "$PREFIX/include"

# libf2c ships the header in two pieces (f2c.h0 + the prototypes in f2ch.add) and its
# makefile concatenates them; nothing includes "f2c.h" until that is done.
# several headers ship as .h0 templates that the makefile installs verbatim
for h in "$SRC"/*.h0; do cp "$h" "${h%.h0}.h"; done
cat "$SRC/f2c.h0" "$SRC/f2ch.add" > "$SRC/f2c.h"
# NOTE: the cat MUST come after the .h0 loop -- f2c.h0 would otherwise overwrite the
# assembled f2c.h and drop every prototype, leaving calls to double-returning
# functions implicitly declared as int.

# arith.h describes the TARGET's float layout. wasm32 is IEEE-754 little-endian with a
# 32-bit long, which is what the native probe reports on this host too, so running it
# natively is safe here -- but it is a host-dependent step, hence the explicit check below.
cc -o "$OBJ/arithchk" -DNO_FPINIT "$SRC/arithchk.c" -lm 2>/dev/null
"$OBJ/arithchk" > "$SRC/arith.h"
grep -q 'IEEE_8087' "$SRC/arith.h" || { echo "arith.h is not little-endian IEEE; wasm needs it" >&2; exit 1; }

CFLAGS="-fwasm-exceptions -O2 -I$SRC -DINTEGER_STAR_8 -Wno-implicit-function-declaration
  -Wno-implicit-int -Wno-deprecated-non-prototype -Wno-parentheses -Wno-return-type"

n=0
for f in "$SRC"/*.c; do
  b="$(basename "$f" .c)"
    # -DINTEGER_STAR_8 only ADDS the `longint` type (f2c.h0:22-27); `integer` stays
  # `long int` = 32-bit on wasm32, matching how we translate ccx. ftell64_ is still
  # skipped -- it wants the 64-bit file API and nothing in ccx calls it.
  case "$b" in arithchk|main|getarg_|iargc_|dtime_|etime_|ftell64_) continue;; esac
  emcc $CFLAGS -c "$f" -o "$OBJ/$b.o" 2>>"$OBJ/warnings.log" || { echo "FAILED: $b" >&2; exit 1; }
  n=$((n+1))
done

# emar appends: without removing it first, members from an earlier run survive
# and reappear as duplicate symbols at link time.
rm -f "$PREFIX/lib/libf2c.a"
emar rcs "$PREFIX/lib/libf2c.a" "$OBJ"/*.o
cp "$SRC/f2c.h" "$PREFIX/include/"
echo "compiled $n objects -> $PREFIX/lib/libf2c.a"
ls -la "$PREFIX/lib/libf2c.a"
