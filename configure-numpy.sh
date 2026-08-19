#!/bin/bash
# Cross-compile numpy's C extensions to wasm32-emscripten and harvest them into
# deps/wasm/lib/numpy-mod/ for the FreeCAD monolith link.
#
# RECONSTRUCTED. This script was referenced by name in configure-gui-weh.sh and
# configure-gui.sh -- "numpy C-extension static libs (built by configure-numpy.sh into
# deps/wasm/lib/numpy-mod)" -- and produced a build-numpy/ directory that
# configure-matplotlib-weh.sh reaches into for numpy's generated headers. It was never
# committed. Same defect as the three force-included headers: a build step that existed
# only on the build machine, invisible because deps/ is gitignored.
#
# What it must produce, dictated by its consumers rather than guessed:
#
#   deps/wasm/lib/numpy-mod/libnpy__multiarray_umath.a   named explicitly, and FIRST, by
#   deps/wasm/lib/numpy-mod/libnpy__pocketfft_umath.a    configure-gui-weh.sh's NPYLIBS --
#   deps/wasm/lib/numpy-mod/libnpy__umath_linalg.a       link order matters, see below
#   deps/wasm/lib/numpy-mod/libnpy_lapack_lite.a
#   deps/wasm/lib/numpy-mod/*.a                          everything else, order-independent
#   build-numpy/**/_numpyconfig.h                        consumed by matplotlib
#   build-numpy/**/__multiarray_api.h
#   build-numpy/**/__ufunc_api.h
#
# MainGui.cpp registers these four under their full dotted names
# (numpy._core._multiarray_umath, numpy.fft._pocketfft_umath, numpy.linalg._umath_linalg,
# numpy.linalg.lapack_lite), so the archive names here and the inittab there have to agree.
#
# Prerequisites: emsdk active, CPython built (host + wasm/pthreads), meson + ninja
# available, and patches/numpy.patch applied -- without it a re-entered
# PyInit__multiarray_umath aborts with "CPU dispatcher tracer already initlized".
set -e
cd "$(dirname "$0")"
ROOT="$PWD"
DW="$ROOT/deps/wasm"
NPY="$ROOT/deps/src/numpy"

[ -d "$NPY" ] || { echo "!! $NPY missing -- fetch numpy first"; exit 1; }

if [ -f "$ROOT/.qtvenv/bin/activate" ]; then
    # shellcheck disable=SC1091
    source "$ROOT/.qtvenv/bin/activate"
fi
# shellcheck disable=SC1091
source "$ROOT/emsdk/emsdk_env.sh" >/dev/null 2>&1

# The cross-file needs absolute paths, so it is generated rather than committed.
bash tools/gen-crossfiles.sh

# Make the HOST interpreter describe the WASM build.
#
# meson resolves numpy's python dependency by asking the interpreter named in the
# cross-file where its headers are. That interpreter is CPython's own host build, so it
# answers with the host include directory, meson puts it FIRST on every command line, and
# the host pyconfig.h wins:
#
#     Include/pyport.h:399: error: "LONG_BIT definition appears wrong for platform
#                                   (bad gcc/glibc config?)."
#
# because the host is 64-bit and wasm32 is not. _PYTHON_SYSCONFIGDATA_NAME is CPython's
# own mechanism for exactly this -- it makes sysconfig read the cross build's data instead
# of the interpreter's own, so the paths and sizes reported are the target's. This is the
# same route pyodide takes. configure-matplotlib-weh.sh works around the identical problem
# by hand for pybind11; this fixes it at the source for anything that asks.
MT="$ROOT/deps/src/cpython/builddir/emscripten-mt"
SYSCFG="$(find "$MT" -maxdepth 2 -name '_sysconfigdata_*emscripten*.py' 2>/dev/null | head -1)"
if [ -n "$SYSCFG" ]; then
    export _PYTHON_SYSCONFIGDATA_NAME="$(basename "$SYSCFG" .py)"
    export PYTHONPATH="$(dirname "$SYSCFG")${PYTHONPATH:+:$PYTHONPATH}"
    echo "cross sysconfig: $_PYTHON_SYSCONFIGDATA_NAME (from $(dirname "$SYSCFG"))"
else
    echo "!! no _sysconfigdata_*emscripten*.py under $MT."
    echo "   Without it the host interpreter reports HOST include paths, meson puts them"
    echo "   first, and every translation unit fails on LONG_BIT. Check build-cpython-mt.sh."
fi

# meson's python= entry points at the non-.exe symlink deliberately (see the cross-file);
# fail here with a sentence rather than inside meson's compiler probe.
HOSTPY="$ROOT/deps/src/cpython/builddir/build/python3-native"
if [ ! -e "$HOSTPY" ]; then
    echo "!! $HOSTPY missing."
    echo "   numpy's code generators run on the HOST python, which is CPython's own build."
    echo "   Run build-cpython.sh first."
    exit 1
fi

# numpy does not build with upstream meson. Its meson_cpu/ CPU-dispatch machinery does
# import('features'), a module that exists only in the meson FORK numpy vendors and ships
# inside its sdist, so a stock meson stops at:
#
#     meson_cpu/x86/meson.build:2:15: ERROR: Module "features" does not exist.
#
# Prefer the vendored copy, and say plainly when it is absent rather than leaving the next
# person to decode that message.
MESON="meson"
for cand in "$NPY/vendored-meson/meson/meson.py" "$NPY/vendored-meson/meson/meson"; do
    if [ -e "$cand" ]; then
        MESON="$(command -v python3) $cand"
        echo "using numpy's vendored meson: $cand"
        break
    fi
done
if [ "$MESON" = "meson" ]; then
    echo "!! no vendored-meson under $NPY -- configuring with the system meson, which will"
    echo "   almost certainly fail on the 'features' module. Use the numpy SDIST"
    echo "   (numpy-<version>.tar.gz from the release page); a git archive omits it."
fi

rm -rf build-numpy
$MESON setup build-numpy "$NPY" --cross-file emscripten-crossfile.meson \
    -Dbuildtype=release -Db_lto=false -Dallow-noblas=true

ninja -C build-numpy

# Harvest: one archive per C extension, each providing its PyInit_*. meson leaves the
# objects in a <name>.so.p directory whose suffix carries the HOST triple -- darwin on the
# build machine, x86_64-linux-gnu in CI -- so match on .so.p and not on any triple.
EMAR="$ROOT/emsdk/upstream/emscripten/emar"
mkdir -p "$DW/lib/numpy-mod"
rm -f "$DW"/lib/numpy-mod/*.a

found=0
while IFS= read -r d; do
    [ -d "$d" ] || continue
    base="$(basename "$d")"
    name="${base%%.*}"          # _multiarray_umath.cpython-313-....so.p -> _multiarray_umath
    objs=$(find "$d" -name '*.o' | wc -l | tr -d ' ')
    [ "$objs" -gt 0 ] || continue
    find "$d" -name '*.o' -print0 | xargs -0 "$EMAR" rcs "$DW/lib/numpy-mod/libnpy_$name.a"
    found=$((found + 1))
done < <(find build-numpy -type d -name '*.so.p')

if [ "$found" = 0 ]; then
    echo "!! no *.so.p object directories under build-numpy -- nothing was harvested."
    exit 1
fi

# The four the link names explicitly must exist, or the FreeCAD link silently loses the
# numpy builtins and every `import numpy` fails at run time instead of at build time.
missing=0
for m in _multiarray_umath _pocketfft_umath _umath_linalg lapack_lite; do
    if [ ! -s "$DW/lib/numpy-mod/libnpy_$m.a" ]; then
        echo "!! missing $DW/lib/numpy-mod/libnpy_$m.a"
        missing=1
    fi
done
[ "$missing" = 0 ] || exit 1

echo "numpy C-extensions harvested to $DW/lib/numpy-mod ($found archives):"
ls -la "$DW/lib/numpy-mod/"
