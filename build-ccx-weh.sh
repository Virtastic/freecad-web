#!/usr/bin/env bash
# Build CalculiX (ccx) as a wasm static library.
#
# Pipeline per Fortran file:  tools/f77ify.py (F90 -> F77)  ->  f2c  ->  emcc
# The native .c files compile directly. Unconvertible Fortran is recorded, not hidden:
# UNCONVERTED.txt lists it, and anything the link actually reaches is either fixed in
# the source (calcstabletimeincvol.f) or aborts with a named message (bridge/ccx_stubs.c).
#
# Requires deps/wasm/lib/{libspooles.a,libf2c.a} -- build-spooles-weh.sh, build-libf2c-weh.sh.
# Output: deps/wasm/lib/libccx.a
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
source "$ROOT/emsdk/emsdk_env.sh" >/dev/null 2>&1
CCX="$ROOT/deps/src/ccx/ccx_2.22/src"
SPOOLES="$ROOT/deps/src/spooles/SPOOLES.2.2"
PREFIX="$ROOT/deps/wasm"
BUILD="$ROOT/build-ccx-weh"
F2C="$ROOT/deps/src/f2c/src/f2c"

test -x "$F2C" || { echo "missing f2c translator at $F2C" >&2; exit 1; }
test -f "$PREFIX/lib/libarpack.a" || { echo "build libarpack first" >&2; exit 1; }
test -f "$PREFIX/lib/libf2c.a" || { echo "build libf2c first" >&2; exit 1; }

rm -rf "$BUILD"; mkdir -p "$BUILD/c" "$BUILD/obj"
: > "$BUILD/UNCONVERTED.txt"

# --- Fortran -----------------------------------------------------------------
# f2c resolves INCLUDE relative to cwd, and ccx includes gauss.f, so the rewritten
# sources have to sit together in one directory and be translated from inside it.
mkdir -p "$BUILD/f77"
for f in "$CCX"/*.f; do
  python3 "$ROOT/tools/f77ify.py" "$f" "$BUILD/f77/$(basename "$f")"
done
# already F77; f77ify rewrites maxval/sum into calls on these
cp "$ROOT/bridge/ccx_reductions.f" "$BUILD/f77/"

cd "$BUILD/f77"
nf=0
for f in *.f; do
  if "$F2C" -a -A -NC1000 -d"$BUILD/c" "$f" >/dev/null 2>"$BUILD/f2c-$f.log" \
     && ! grep -q '^Error' "$BUILD/f2c-$f.log"; then
    nf=$((nf+1))
    rm -f "$BUILD/f2c-$f.log"        # succeeded: nothing to learn
    # NOTE: the failure branch deliberately KEEPS its log. Deleting it
    # unconditionally is why 68 routines were known to be stubbed but
    # nobody could say WHY -- and a stubbed routine silently does nothing
    # at run time. The reason is what makes tools/f77ify.py extendable.
  else
    echo "$f" >> "$BUILD/UNCONVERTED.txt"
    rm -f "$BUILD/c/${f%.f}.c"
  fi
done
cd "$ROOT"

# wasm is strictly typed and CalculiX.h declares Fortran subroutines `void`, while f2c
# emits them returning int -- wasm-ld turns that mismatch into a hard link error.
CFLAGS="-fwasm-exceptions -O2 -DINTEGER_STAR_8 -I$PREFIX/include -I$SPOOLES -I$CCX
  -DARCH=Linux -DSPOOLES -DARPACK -DMATRIXSTORAGE -DNETWORKOUT
  -Wno-implicit-function-declaration -Wno-implicit-int -Wno-int-conversion
  -Wno-return-type -Wno-parentheses -Wno-format -Wno-deprecated-non-prototype"

# The ABI passes. All four are idempotent, so the second stub round can simply re-run
# them over the whole directory rather than trying to patch one file consistently.
# libf2c's routines really do return int, so their declarations must be left alone.
# Only libf2c: the hand-written C in bridge/ returns void deliberately, precisely so the
# generated declarations (which this pass rewrites to void) match it. llvm-nm reports no
# return type, so anything listed here is asserted to be int-returning, not discovered.
keep_int_list() {
  # Which libf2c routines really return int, read from their ANSI definitions. It is
  # genuinely mixed -- s_stop returns int, s_copy returns void -- so this cannot be
  # assumed either way, and llvm-nm does not report return types.
  python3 - "$ROOT/deps/src/f2c/libf2c" > "$BUILD/keep-int.txt" <<'PYEOF'
import pathlib, re, sys
# libf2c writes the return type on its own line as often as not, so a line-anchored
# grep misses roughly half of them (system_ among them).
pat = re.compile(r'(?:^|\n)\s*(?:int|integer)\s*\n?\s*([a-z_0-9]+)\s*\(', re.M)
names = set()
for f in sorted(pathlib.Path(sys.argv[1]).glob('*.c')):
    names |= set(pat.findall(f.read_text(errors='replace')))
print('\n'.join(sorted(names)))
PYEOF
}

abi_passes() {
  # f2c appends two underscores to names containing one; gfortran (which ccx's C
  # files are written against) appends one.
  python3 "$ROOT/tools/f2c_single_underscore.py" "$BUILD/c" "$BUILD/f77" --c-names "$CCX"
  python3 "$ROOT/tools/f2c_subroutine_void.py" "$BUILD/c" --exclude-from "$BUILD/keep-int.txt"

# ccx's C callers omit f2c's hidden CHARACTER-length arguments; on wasm that arity
# mismatch becomes a trapping stub rather than a harmless ignored register.
python3 "$ROOT/tools/f2c_strip_ftnlen.py" "$BUILD/c" --also "$PREFIX/lib/ccx-abi-arpack.txt"
# debug_/timing_ are ARPACK's COMMON blocks; ccx's Fortran declares them only to talk
# to it, so libarpack.a owns the definition and every copy here is extern.
python3 "$ROOT/tools/f2c_dedupe_commons.py" "$BUILD/c" --extern debug_,timing_
  # ccx calls a few of its own routines with more arguments than they declare; harmless
  # natively, a trapping stub on wasm. Arities come from a recorded wasm-ld log so this
  # reflects what the linker actually saw rather than a hand-maintained list.
  python3 "$ROOT/tools/f2c_pad_arity.py" "$BUILD/c" "$ROOT/ccx-arity.log" --defs-also "$CCX"
}

stub_round() {  # $1 = file listing .f basenames to replace with aborting stubs
  python3 "$ROOT/tools/ccx_make_stubs.py" "$1" "$BUILD/f77" "$BUILD/stubs"
  ( cd "$BUILD/stubs" && for f in *.f; do
      [ -f "$f" ] || continue
      "$F2C" -a -A -NC1000 -d"$BUILD/c" "$f" >/dev/null 2>&1 || echo "STUB-FAIL $f" >> "$BUILD/UNCONVERTED.txt"
    done )
  abi_passes
}

# compiled early: keep_int_list reads their symbols, and the ABI passes need that list
mkdir -p "$BUILD/obj"
emcc $CFLAGS -c "$ROOT/bridge/ccx_stubs.c" -o "$BUILD/obj/c_ccx_stubs.o" 2>/dev/null || true
emcc $CFLAGS -c "$ROOT/bridge/ccx_fortran_rt.c" -o "$BUILD/obj/c_ccx_fortran_rt.o" 2>/dev/null || true
keep_int_list

stub_round "$BUILD/UNCONVERTED.txt"

# A file can translate cleanly and still not compile. Those need stubbing too, and a
# syntax-only pass finds them without paying for codegen twice.
: > "$BUILD/needs-stub.txt"
for f in "$BUILD"/c/*.c; do
  emcc $CFLAGS -fsyntax-only "$f" 2>/dev/null || {
    b="$(basename "$f" .c)"
    echo "$b.f" >> "$BUILD/needs-stub.txt"
    echo "CC-FAIL $b (stubbed)" >> "$BUILD/UNCONVERTED.txt"
    rm -f "$f"
  }
done
if [ -s "$BUILD/needs-stub.txt" ]; then
  echo "stubbing $(wc -l < "$BUILD/needs-stub.txt" | tr -d ' ') routines that translated but did not compile"
  stub_round "$BUILD/needs-stub.txt"
fi

# --- compile -----------------------------------------------------------------
# ARCH must be the bare token `Linux`, not a string: CalculiX.h:25 does
# `#if ARCH == Linux`. (ccx's Makefile writes -DARCH="Linux" and relies on make
# handing it to the shell, which strips the quotes; $CFLAGS expansion does not.)
# -DINTEGER_STAR_8 must match how libf2c was built (it only adds `longint`).
# ARPACK is required, not optional: feasibledirection.c -- called unconditionally
# from ccx_2.22.c -- is entirely inside `#ifdef ARPACK`.

nc=0; failed=0
compile() {  # $1=source $2=objname
  # Retry once. A failure with nothing on stderr is emcc being killed under memory
  # pressure, not a real error -- and a CC-FAIL silently stubs the routine, so twelve
  # of them (subspace, e_c3d_rhs_th, stop ...) were being dropped from one build and
  # not the next. A genuine error fails twice and still gets reported.
  for attempt in 1 2; do
    if emcc $CFLAGS -c "$1" -o "$BUILD/obj/$2.o" 2>>"$BUILD/compile-errors.log"; then
      return 0
    fi
  done
  echo "CC-FAIL $1" >> "$BUILD/UNCONVERTED.txt"; return 1
}

for f in "$BUILD"/c/*.c; do
  compile "$f" "f_$(basename "$f" .c)" && nf2=$((${nf2:-0}+1)) || failed=$((failed+1))
done
# routines that cannot be translated at all -- see bridge/ccx_stubs.c
compile "$ROOT/bridge/ccx_stubs.c" "c_ccx_stubs" && nc=$((nc+1)) || failed=$((failed+1))
# real implementations of things f2c does not provide (dnrm2, xerbla, F90 intrinsics)
compile "$ROOT/bridge/ccx_fortran_rt.c" "c_ccx_fortran_rt" && nc=$((nc+1)) || failed=$((failed+1))
# Threading. Two modes, and the default is the SAFE one.
#
# ccx parallelises assembly and stress recovery by handing each thread a disjoint range of
# elements, then joining immediately. This module is not built with -pthread, so emscripten's
# pthread_create is a stub that FAILS -- and ccx never checks the return value. The workers
# simply never ran: the matrix came out identically zero, SPOOLES reported it singular, and
# nothing anywhere said why. bridge/ccx_threads.c wraps pthread_create to run each worker
# inline, which is why the solver produces numbers at all. It serialises what would have been
# parallel -- that is the "single-threaded CalculiX" limit users feel on large FEM jobs.
#
# FCWEB_CCX_PTHREADS=1 builds it for real instead: -pthread, no wrap, ccx's own
# pthread_create. The ingredients are present -- the main app already runs -pthread with
# PTHREAD_POOL_SIZE=16 and the site is cross-origin isolated, so SharedArrayBuffer exists.
#
# UNVERIFIED, deliberately opt-in. Before believing a threaded build, run the four decks:
#   node scratchpad/ccxval/run.js        # elas, freq, plast, therm
#   node scratchpad/ccxe2e/run-prod.js   # end to end through the browser bridge
# Results must MATCH the current numbers, not merely converge -- a race in the assembly would
# show up as a slightly different answer, not as a crash. And measure before celebrating: if
# SPOOLES factorisation dominates the runtime, parallel assembly may buy very little, which
# is worth knowing before spending a day on it.
if [ "${FCWEB_CCX_PTHREADS:-0}" = "1" ]; then
  echo "[ccx] building WITH pthreads -- ccx_threads.c wrap omitted (UNVERIFIED path)" >&2
  CFLAGS="$CFLAGS -pthread"
else
  compile "$ROOT/bridge/ccx_threads.c" "c_ccx_threads" && nc=$((nc+1)) || failed=$((failed+1))
fi

for f in "$CCX"/*.c; do
  b="$(basename "$f" .c)"
  [ "$b" = "ccx_2.22" ] && continue        # main(); the bridge supplies its own entry
  compile "$f" "c_$b" && nc=$((nc+1)) || failed=$((failed+1))
done

# emar appends: without removing it first, members from an earlier run survive
# and reappear as duplicate symbols at link time.
rm -f "$PREFIX/lib/libccx.a"
emar rcs "$PREFIX/lib/libccx.a" "$BUILD"/obj/*.o
echo "fortran translated : $nf / $(ls "$CCX"/*.f | wc -l | tr -d ' ')"
echo "fortran compiled   : ${nf2:-0}"
echo "native C compiled  : $nc"
echo "failed             : $failed  (see $BUILD/UNCONVERTED.txt)"
ls -la "$PREFIX/lib/libccx.a"
