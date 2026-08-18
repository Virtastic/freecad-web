#!/bin/bash
# Spike (c) prerequisite: cross-build CPython 3.13 for wasm32-emscripten (node
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
CONFIG_SITE="$SRC/Tools/wasm/config.site-wasm32-emscripten" \
emconfigure ../../configure -C \
  --host=wasm32-unknown-emscripten \
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
NM="$ROOT/emsdk/upstream/emscripten/emnm"
missing=0
for sym in _PyEM_TrampolineCall_Reflection _PyEM_TrampolineCall_JavaScript _PyEM_detect_type_reflection; do
  if "$NM" libpython3.13.a 2>/dev/null | grep -q "T $sym"; then
    echo "  ok  $sym"
  else
    echo "  MISSING: $sym"
    missing=1
  fi
done
if [ "$missing" != 0 ]; then
  echo "ERROR: libpython3.13.a has no trampoline symbols. PY_CALL_TRAMPOLINE did not reach" >&2
  echo "       the compiler, so JSPI cannot suspend across a Python call and every modal" >&2
  echo "       dialog will return the wrong answer -- silently. See BUILD-WEH.md." >&2
  ls -la ./Python/emscripten_trampoline.o 2>/dev/null >&2
  exit 1
fi

