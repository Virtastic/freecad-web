#!/usr/bin/env bash
# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) Virtastic
# Link the CalculiX wasm module that FreeCAD-Web calls instead of the ccx binary.
# Run build-{spooles,libf2c,arpack,ccx}-weh.sh first.
#
# Produces play-gui/ccx.{js,wasm}: a MODULARIZEd module fetched on first use, so the
# main FreeCAD.wasm does not grow.
#
# Two link flags are load-bearing:
#   --wrap=pthread_create/join  ccx runs assembly and stress recovery on threads; this
#                               module is not built with -pthread, so without the wrap
#                               the workers never run and every matrix comes out zero.
#   --start-group               libccx and libarpack reference each other.
# ENVIRONMENT includes node so the module can be exercised outside a browser.
# -sWASM_BIGINT is no longer passed: BigInt integration is the default in emscripten 6.x and
# the flag is deprecated. It was here to dodge the i64 legalization pass, which called emsdk
# 3.1.70's wasm-emscripten-finalize (binaryen v119) -- and that could not parse wasm-EH. Both
# the SDK and that problem are gone.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
source "$ROOT/toolchain/env.sh"
PREFIX="$ROOT/deps/wasm"
CCX="$ROOT/deps/src/ccx/ccx_2.22/src"
OUT="$ROOT/play-gui"
OBJ="$ROOT/build-ccx-weh/module"

# Threading, matched to how libccx.a was built (see build-ccx-weh.sh).
#
# Serial (default): bridge/ccx_threads.c supplies __wrap_pthread_create/__wrap_pthread_join,
# so the link must ask for those wraps or ccx's real pthread_create is used -- and on a
# non-pthread build that is a stub which silently fails, leaving an all-zero matrix.
#
# Threaded: ccx_threads.c is NOT compiled, so there is no __wrap_* to bind. Leaving the
# --wrap flags in place then makes wasm-ld SEGFAULT inside ImportSection::addImport rather
# than report a missing symbol -- measured, and the reason this is a variable now.
if [ "${FCWEB_CCX_PTHREADS:-0}" = "1" ]; then
  CCX_THREAD_LINK="-pthread -sPTHREAD_POOL_SIZE=4"
  echo "[ccx-module] linking WITH pthreads (no --wrap)" >&2
else
  CCX_THREAD_LINK="-Wl,--wrap=pthread_create -Wl,--wrap=pthread_join"
fi

for l in libccx libarpack libspooles libf2c; do
  test -f "$PREFIX/lib/$l.a" || { echo "missing $PREFIX/lib/$l.a" >&2; exit 1; }
done
mkdir -p "$OBJ"

CFLAGS="-fwasm-exceptions -O2 -DINTEGER_STAR_8 -I$PREFIX/include -I$CCX
  -Ideps/src/spooles/SPOOLES.2.2 -DARCH=Linux -DSPOOLES -DARPACK -DMATRIXSTORAGE
  -DNETWORKOUT -w"

# ccx's main() becomes a callable entry point
# 16 GiB, matching the engine. This is a separate wasm module with its own heap, so
# without an explicit ceiling it would default to 2 GB and gain nothing from wasm64 --
# which for ccx is exactly the workload the extra address space is for.
emcc $CFLAGS -Dmain=fcweb_ccx_main -c "$CCX/ccx_2.22.c" -o "$OBJ/ccx_main.o"
emcc $CFLAGS -c "$ROOT/ccx_wasm_main.c" -o "$OBJ/wrapper.o"

emcc -fwasm-exceptions -O2 "$OBJ/ccx_main.o" "$OBJ/wrapper.o" \
  -Wl,--start-group "$PREFIX/lib/libccx.a" "$PREFIX/lib/libarpack.a" \
                    "$PREFIX/lib/libspooles.a" "$PREFIX/lib/libf2c.a" -Wl,--end-group \
  $CCX_THREAD_LINK \
  -o "$OUT/ccx.js" \
  -sMODULARIZE=1 \
  -sEXPORT_NAME=CcxModule \
  \
  -sEXPORTED_FUNCTIONS=_fcweb_ccx_run,_fcweb_ccx_version,_malloc,_free \
  -sEXPORTED_RUNTIME_METHODS=FS,ccall,cwrap,stringToUTF8,UTF8ToString,lengthBytesUTF8 \
  -sFORCE_FILESYSTEM=1 \
  -sALLOW_MEMORY_GROWTH=1 \
  -sINITIAL_MEMORY=268435456 \
  -sMAXIMUM_MEMORY=17179869184 \
  -sSTACK_SIZE=16MB \
  -sEXIT_RUNTIME=0 \
  -sASSERTIONS=0 \
  -sENVIRONMENT=web,worker,node \
  -sERROR_ON_UNDEFINED_SYMBOLS=0

ls -la "$OUT/ccx.js" "$OUT/ccx.wasm"
echo "CalculiX module -> $OUT/ccx.{js,wasm}"
