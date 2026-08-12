#!/usr/bin/env bash
# Build ARPACK + the BLAS/LAPACK it needs as a wasm static library.
#
# CalculiX is not buildable without ARPACK: feasibledirection.c -- which ccx_2.22.c calls
# unconditionally -- is entirely inside `#ifdef ARPACK`. ARPACK also supplies the lsame_
# and xerbla_ that ccx's own dgesv.f references. It backs frequency/modal analysis.
#
# netlib's arpack96 tarballs now 404, so this uses arpack-ng (which does not bundle
# BLAS/LAPACK) plus reference LAPACK.
#
# These are essentially F77, but arpack-ng uses a few F2003 spellings, so the same
# tools/f77ify.py pass CalculiX needs is applied here too. LAPACK is restricted to the double-precision and auxiliary
# routines: ccx is double-only, and building the complex/single trees would triple the
# compile for code that is never linked. Files f2c rejects (a few use RECURSIVE) are
# recorded rather than hidden; unused archive members simply never get pulled in.
#
# Output: deps/wasm/lib/libarpack.a
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
source "$ROOT/emsdk/emsdk_env.sh" >/dev/null 2>&1
A="$ROOT/deps/src/arpack/arpack-ng-3.9.1"
L="$ROOT/deps/src/lapack/lapack-3.12.0"
PREFIX="$ROOT/deps/wasm"
BUILD="$ROOT/build-arpack-weh"
F2C="$ROOT/deps/src/f2c/src/f2c"

rm -rf "$BUILD"; mkdir -p "$BUILD/f77" "$BUILD/c" "$BUILD/obj"
: > "$BUILD/UNCONVERTED.txt"

collect() {  # copy sources into one flat dir; f2c resolves INCLUDE relative to cwd
  for f in "$@"; do [ -f "$f" ] && cp -n "$f" "$BUILD/f77/" 2>/dev/null || true; done
}
collect "$A"/UTIL/*.f "$L"/BLAS/SRC/*.f
# second.f times itself with the ETIME intrinsic, which f2c cannot translate, so it
# gets stubbed -- and the stub aborts the moment ARPACK starts an eigenvalue solve.
# arpack-ng ships second_NONE.f for exactly this case; keep that one only.
rm -f "$BUILD/f77/second.f"
# double-precision + auxiliary only: drop the c/s/z (complex/single) trees, in both
# ARPACK and LAPACK. ccx is double-only, and f2c chokes on the complex sources anyway.
for f in "$A"/SRC/*.f "$L"/SRC/*.f; do
  case "$(basename "$f")" in [cszCSZ]*) continue;; esac
  cp -n "$f" "$BUILD/f77/" 2>/dev/null || true
done
# arpack-ng keeps its debug/stat commons in these, and SRC/*.f INCLUDEs them
cp -n "$A"/SRC/*.h "$BUILD/f77/" 2>/dev/null || true

# arpack-ng is F77 apart from a few F2003 spellings, so the same rewriter CalculiX
# needs is run over it -- cheaper than special-casing dsaupd/dseupd/dnaupd/dneupd,
# which are exactly the entry points ccx calls.
for f in "$BUILD"/f77/*.f; do
  python3 "$ROOT/tools/f77ify.py" "$f" "$f.tmp" && mv "$f.tmp" "$f"
done

cd "$BUILD/f77"
n=0; bad=0
for f in *.f; do
  if "$F2C" -a -A -NC1000 -d"$BUILD/c" "$f" >/dev/null 2>"$BUILD/e.log" && ! grep -q '^Error' "$BUILD/e.log"; then
    n=$((n+1))
  else
    echo "$f" >> "$BUILD/UNCONVERTED.txt"; rm -f "$BUILD/c/${f%.f}.c"; bad=$((bad+1))
  fi
done
rm -f "$BUILD/e.log"
cd "$ROOT"

# same ABI adjustments as CalculiX -- see the two tools for why
# f2c appends two underscores to names containing one; gfortran (which ccx's C
# files are written against) appends one.
python3 "$ROOT/tools/f2c_single_underscore.py" "$BUILD/c" "$BUILD/f77"

# Same treatment as CalculiX: anything f2c rejected gets a same-signature stub that
# aborts, so an unconvertible routine is a named runtime error rather than a link
# failure. second.f is the common case (it calls the etime intrinsic).
python3 "$ROOT/tools/ccx_make_stubs.py" "$BUILD/UNCONVERTED.txt" "$BUILD/f77" "$BUILD/stubs"
( cd "$BUILD/stubs" 2>/dev/null && for f in *.f; do
    [ -f "$f" ] || continue
    "$F2C" -a -A -NC1000 -d"$BUILD/c" "$f" >/dev/null 2>&1 || true
  done )

ABI="$PREFIX/lib/ccx-abi-arpack.txt"
rm -f "$ABI"
python3 "$ROOT/tools/f2c_subroutine_void.py" "$BUILD/c" --emit "$ABI"
python3 "$ROOT/tools/f2c_strip_ftnlen.py" "$BUILD/c" --emit "$ABI"
python3 "$ROOT/tools/f2c_dedupe_commons.py" "$BUILD/c"

CFLAGS="-fwasm-exceptions -O2 -DINTEGER_STAR_8 -I$PREFIX/include
  -Wno-implicit-function-declaration -Wno-implicit-int -Wno-int-conversion
  -Wno-return-type -Wno-parentheses -Wno-format -Wno-deprecated-non-prototype"

nc=0
for f in "$BUILD"/c/*.c; do
  b="$(basename "$f" .c)"
  emcc $CFLAGS -c "$f" -o "$BUILD/obj/$b.o" 2>>"$BUILD/compile-errors.log" && nc=$((nc+1)) \
    || echo "CC-FAIL $b" >> "$BUILD/UNCONVERTED.txt"
done

# emar appends: without removing it first, members from an earlier run survive
# and reappear as duplicate symbols at link time.
OBJ_STUB="$BUILD/obj/zz_ccx_stubs.o"
rm -f "$PREFIX/lib/libarpack.a"
emcc $CFLAGS -c "$ROOT/bridge/ccx_stubs.c" -o "$OBJ_STUB" 2>/dev/null || true
emar rcs "$PREFIX/lib/libarpack.a" "$BUILD"/obj/*.o
echo "translated : $n (f2c rejected $bad)"
echo "compiled   : $nc"
ls -la "$PREFIX/lib/libarpack.a"
