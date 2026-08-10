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
  if "$F2C" -a -A -d"$BUILD/c" "$f" >/dev/null 2>"$BUILD/e.log" && ! grep -q '^Error' "$BUILD/e.log"; then
    n=$((n+1))
  else
    echo "$f" >> "$BUILD/UNCONVERTED.txt"; rm -f "$BUILD/c/${f%.f}.c"; bad=$((bad+1))
  fi
done
rm -f "$BUILD/e.log"
cd "$ROOT"

# same ABI adjustments as CalculiX -- see the two tools for why
python3 "$ROOT/tools/f2c_subroutine_void.py" "$BUILD/c"
python3 "$ROOT/tools/f2c_strip_ftnlen.py" "$BUILD/c"

# -fcommon: f2c emits a Fortran COMMON block as a tentative definition in every file
# that declares it (ARPACK's debug_/timing_ are in most of them). The legacy
# common-symbol model merges those; clang defaults to -fno-common, which makes each
# one a hard definition and the link a pile of duplicate symbols.
CFLAGS="-fwasm-exceptions -O2 -fcommon -DINTEGER_STAR_8 -I$PREFIX/include
  -Wno-implicit-function-declaration -Wno-implicit-int -Wno-int-conversion
  -Wno-return-type -Wno-parentheses -Wno-format -Wno-deprecated-non-prototype"

nc=0
for f in "$BUILD"/c/*.c; do
  b="$(basename "$f" .c)"
  emcc $CFLAGS -c "$f" -o "$BUILD/obj/$b.o" 2>>"$BUILD/compile-errors.log" && nc=$((nc+1)) \
    || echo "CC-FAIL $b" >> "$BUILD/UNCONVERTED.txt"
done

emar rcs "$PREFIX/lib/libarpack.a" "$BUILD"/obj/*.o
echo "translated : $n (f2c rejected $bad)"
echo "compiled   : $nc"
ls -la "$PREFIX/lib/libarpack.a"
