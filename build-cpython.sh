#!/bin/bash
# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) Virtastic
# Spike (c) prerequisite: cross-build CPython 3.13 for wasm64-emscripten (node
# target = threads + direct FS). Produces libpython3.13.a + pyconfig.h to embed.
set -e
cd "$(dirname "$0")"
. toolchain/env.sh
SRC="$ROOT/deps/src/cpython"
cd "$SRC"

# Stage 1: host (build) interpreter, same source tree/version.
if [ ! -x "$SRC/builddir/build/python" ] && [ ! -x "$SRC/builddir/build/python.exe" ]; then
  echo "=== stage 1: host python ==="
  mkdir -p builddir/build
  ( cd builddir/build && ../../configure -C >/dev/null && make -j8 )
fi
BUILD_PY="$SRC/builddir/build/python"
[ -x "$BUILD_PY" ] || BUILD_PY="$SRC/builddir/build/python.exe"
echo "host python: $BUILD_PY"

# Stage 2: emscripten cross build (node flavor).
# See build-cpython-mt.sh for why -DPY_CALL_TRAMPOLINE=1 has to be here: CPython's own
# build never defines it, and without it the trampoline silently vanishes.
export EMCC_CFLAGS="${EMCC_CFLAGS:-} -DPY_CALL_TRAMPOLINE=1"
echo "=== stage 2: emscripten cross build ==="
mkdir -p builddir/emscripten
cd builddir/emscripten
CONFIG_SITE="$ROOT/toolchain/config.site-wasm64-emscripten" \
emconfigure ../../configure -C \
  --host=wasm64-unknown-emscripten \
  --build="$($SRC/config.guess)" \
  --with-emscripten-target=node \
  --with-build-python="$BUILD_PY"
emmake make -j8
echo "=== cpython emscripten build done ==="
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

