#!/bin/bash
# Rebuild CPython 3.13 emscripten target WITH wasm pthreads (-pthread/atomics)
# so it links cleanly with -pthread OCCT/Boost/Qt. Separate builddir.
set -e
cd "$(dirname "$0")"
. toolchain/env.sh
SRC="$ROOT/deps/src/cpython"
# CPython names the host binary python.exe on a case-insensitive filesystem (macOS) and
# plain python elsewhere. Hardcoding python.exe made this script macOS-only, so it could
# never have run in CI or on Linux. build-cpython.sh already probed for both; match it.
BUILD_PY="$SRC/builddir/build/python"
[ -x "$BUILD_PY" ] || BUILD_PY="$SRC/builddir/build/python.exe"
[ -x "$BUILD_PY" ] || { echo "ERROR: no host python under $SRC/builddir/build -- run build-cpython.sh first." >&2; exit 1; }
echo "host python: $BUILD_PY"
# -DPY_CALL_TRAMPOLINE=1 is NOT optional and NOT supplied by CPython's own build.
# Python/emscripten_trampoline.c opens with `#if defined(PY_CALL_TRAMPOLINE)` on line 1
# and only includes <Python.h> on line 4, INSIDE the guard -- so pyconfig.h can never
# enable it, and neither configure.ac, config.site-wasm32-emscripten nor Makefile.pre.in
# define it (checked against v3.13.3). Without it the file compiles to a ~273-byte empty
# object AND pycore_emscripten_trampoline.h:28 takes its #else branch, so there is no
# trampoline at all and patches/cpython-ctypes-wasm.patch is dead code. The symptom is
# not a build error: it is JSPI failing to suspend across a Python call, i.e. every modal
# dialog quietly returning the wrong answer. BUILD-WEH.md has documented this since the
# beginning; no script had ever passed the flag.
export EMCC_CFLAGS="-pthread -DPY_CALL_TRAMPOLINE=1"   # atomics+bulk-memory, and the trampoline
rm -rf "$SRC/builddir/emscripten-mt" && mkdir -p "$SRC/builddir/emscripten-mt"
cd "$SRC/builddir/emscripten-mt"
CONFIG_SITE="$SRC/Tools/wasm/config.site-wasm32-emscripten" \
emconfigure ../../configure -C \
  --host=wasm32-unknown-emscripten \
  --build="$($SRC/config.guess)" \
  --with-emscripten-target=node \
  --with-build-python="$BUILD_PY"
emmake make -j8
echo "=== cpython-mt build done ==="
ls -la libpython3.13.a pyconfig.h 2>/dev/null
# The trampoline is the thing this whole build exists to get right, and its failure is
# SILENT, so assert it rather than trusting the exit code. Without -DPY_CALL_TRAMPOLINE=1
# above, Python/emscripten_trampoline.c compiles to a ~273-byte empty object and
# pycore_emscripten_trampoline.h:28 takes its #else branch -- no trampoline at all, and
# patches/cpython-ctypes-wasm.patch becomes dead code.
#
# Only _PyEM_TrampolineCall_Reflection is an ordinary C function. The other three
# (_PyEM_TrampolineCall_JavaScript, _PyEM_detect_type_reflection, _PyEM_CountFuncParams)
# are EM_JS, which emscripten emits as JS-library imports plus __em_js__ metadata rather
# than text symbols -- so demanding "T" for those fails on a perfectly good build. That is
# exactly what CI run 32140673586 did: Reflection present, build correct, assertion wrong.
NM="$ROOT/emsdk/upstream/emscripten/emnm"
syms="$("$NM" libpython3.13.a 2>/dev/null || true)"
missing=0
# The decisive one: a plain C definition that only exists when the guard was satisfied.
if printf '%s' "$syms" | grep -q "T _PyEM_TrampolineCall_Reflection"; then
  echo "  ok  _PyEM_TrampolineCall_Reflection (C definition -- the guard was on)"
else
  echo "  MISSING: _PyEM_TrampolineCall_Reflection"
  missing=1
fi
# The EM_JS half: accept either a text symbol or the __em_js__ metadata emscripten emits.
for sym in _PyEM_TrampolineCall_JavaScript _PyEM_detect_type_reflection _PyEM_CountFuncParams; do
  if printf '%s' "$syms" | grep -qE "(T|D) $sym|__em_js__$sym"; then
    echo "  ok  $sym (EM_JS)"
  else
    echo "  MISSING: $sym"
    missing=1
  fi
done
if [ "$missing" != 0 ]; then
  echo "ERROR: libpython3.13.a is missing trampoline symbols. If _PyEM_TrampolineCall_Reflection" >&2
  echo "       is the missing one, PY_CALL_TRAMPOLINE did not reach the compiler: JSPI then" >&2
  echo "       cannot suspend across a Python call and every modal dialog returns the wrong" >&2
  echo "       answer, silently. See BUILD-WEH.md." >&2
  ls -la ./Python/emscripten_trampoline.o 2>/dev/null >&2
  exit 1
fi

