#!/bin/bash
# Build weh-objs/*.o -- the objects that are linked into FreeCAD.wasm but are NOT built by
# cmake. configure-gui-weh.sh names all seven on CMAKE_EXE_LINKER_FLAGS, so the link fails
# without them, and until now they existed only as em++ command lines in comments and in
# BUILD-WEH.md. That is the same uncaptured-build-machine-state defect that produced the
# CalculiX problem: the objects were on one machine's disk and nowhere else.
#
# Each object is verified by SYMBOL after compiling, not merely by exit status. An empty
# object is exactly what this repository has already shipped once -- emscripten_trampoline.c
# silently produced a 273-byte object when a -D was missing, and the whole of JSPI went with
# it -- and a link with -sERROR_ON_UNDEFINED_SYMBOLS=0 turns a missing PyInit_ into a
# runtime trap in the browser rather than a build failure.
set -e
cd "$(dirname "$0")"
. toolchain/env.sh

OUT="$ROOT/weh-objs"
CPY="$ROOT/deps/src/cpython"
PYMT="$CPY/builddir/emscripten-mt"
QT="$ROOT/qt/6.9.0/wasm_mt_weh"
mkdir -p "$OUT"

# -fwasm-exceptions and -pthread must match the rest of the build. Mixing exception models
# in one link is ROADMAP 12's OCCT defect; mixing -pthread is worse, because the atomics and
# TLS ABI differ and the failure is a trap at run time, not a diagnostic.
COMMON="-fwasm-exceptions -pthread -O2"

# The three Python builtin modules need Python.h, and CPython does not ship pyconfig.h in
# Include/ -- configure generates it into the build tree. Assemble one directory holding
# both, the same way every other lane here has had to.
PYINC="$CPY/Include"
if [ ! -f "$CPY/Include/pyconfig.h" ]; then
    PYINC="$ROOT/build-pyinc-wasm"
    if [ ! -f "$PYINC/Python.h" ] || [ ! -f "$PYINC/pyconfig.h" ]; then
        [ -f "$PYMT/pyconfig.h" ] || { echo "ERROR: no wasm pyconfig.h under $PYMT" >&2; exit 1; }
        rm -rf "$PYINC" && mkdir -p "$PYINC"
        cp -r "$CPY/Include/." "$PYINC/"
        cp "$PYMT/pyconfig.h" "$PYINC/pyconfig.h"
    fi
fi
PYFLAGS="-I$PYINC -I$CPY/Include/internal"

# spe_sanitize.cpp includes <QtCore/private/qthread_p.h>. Qt keeps private headers under a
# version directory, so the public include path alone is not enough.
QTVER="$(ls -d "$QT"/include/QtCore/6.* 2>/dev/null | head -1)"
QTFLAGS="-I$QT/include -I$QT/include/QtCore"
[ -n "$QTVER" ] && QTFLAGS="$QTFLAGS -I$QTVER -I$QTVER/QtCore"

echo "  python include: $PYINC"
echo "  qt include:     $QT/include${QTVER:+ (+ private $QTVER)}"

# file : compiler : extra flags : a symbol the object MUST define
#
# The symbol column is what makes this script worth having over a for-loop. Every entry is a
# name the link resolves against; if the object comes out empty the build says so here
# instead of the browser saying it later.
#
# Pick a symbol the file DEFINES, not one you expect it to. gl_legacy_stubs.c was listed as
# glBegin, which it deliberately does not define -- emscripten's LEGACY_GL_EMULATION already
# supplies that one, and this file exists only for the entry points the emulation LACKS.
#
# wasm_event_dispatch.cpp goes with -sEXPORTED_FUNCTIONS+=_fcweb_dispatch_event and
# -sASYNCIFY_EXPORTS=fcweb_run_python,fcweb_dispatch_event, both of which the recorded
# link command scratchpad/linkcmds/fc-linkcmd-weh.sh already carries. NOTE that
# configure-gui-weh.sh's own linker flags do NOT -- it lists neither the object nor the
# two flags -- so a link driven from the cmake target alone leaves Qt DOM events on a
# non-promising stack and every nested event loop entered from a real mouse or key event
# traps with "SuspendError: trying to suspend without WebAssembly.promising".
#
# dialog_exec_wrap.cpp is deliberately absent: it goes with
# -Wl,--wrap=_ZN7QDialog4execEv, which the current configure-gui-weh.sh link line does not
# use (an older link command in scratchpad/linkcmds does). Adding the object without the
# --wrap flag would link a wrapper nothing calls.
UNITS="
postevent_wrap.c|emcc||__wrap__ZN16QCoreApplication9postEventEP7QObjectP6QEventi
fcweb_export_stub.c|emcc||fcweb_run_python
gl_legacy_stubs.c|emcc||glAccum
spe_sanitize.cpp|em++|QT|__wrap__ZN23QCoreApplicationPrivate13notify_helperEP7QObjectP6QEvent
fcweb_dlg_module.cpp|em++|PY|PyInit__fcwebdlg
fcweb_gmsh_module.cpp|em++|PY|PyInit__fcwebgmsh
fcweb_ccx_module.cpp|em++|PY|PyInit__fcwebccx
wasm_event_dispatch.cpp|em++|QT|fcweb_dispatch_event
"

NM="$ROOT/emsdk/upstream/bin/llvm-nm"
[ -x "$NM" ] || NM="$(command -v llvm-nm || command -v nm || true)"

fail=0
echo "$UNITS" | while IFS='|' read -r src cc kind want; do
    [ -n "$src" ] || continue
    [ -f "$src" ] || { echo "  MISSING SOURCE  $src"; exit 1; }
    obj="$OUT/${src%.*}.o"
    extra=""
    case "$kind" in
        PY) extra="$PYFLAGS" ;;
        QT) extra="$QTFLAGS" ;;
    esac
    if ! $cc $COMMON $extra -c "$src" -o "$obj" 2>/tmp/weh-obj-err.txt; then
        echo "  FAILED   $src"
        sed 's/^/      /' /tmp/weh-obj-err.txt | head -20
        exit 1
    fi
    # An object that compiled but defines nothing is the failure mode worth catching.
    if [ -n "$NM" ] && ! "$NM" --defined-only "$obj" 2>/dev/null | grep -q "$want"; then
        echo "  NO SYMBOL $src -> $(basename "$obj") does not define $want"
        "$NM" --defined-only "$obj" 2>/dev/null | head -8 | sed 's/^/      /'
        exit 1
    fi
    echo "  ok       $(basename "$obj")  ($want, $(wc -c <"$obj" | tr -d ' ') bytes)"
done || fail=1

[ "$fail" = 0 ] || { echo "ERROR: weh-objs did not build" >&2; exit 1; }
echo "weh-objs: $(ls -1 "$OUT"/*.o 2>/dev/null | wc -l | tr -d ' ') object(s) in $OUT"
