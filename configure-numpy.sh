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

# meson's python= entry points at the non-.exe symlink deliberately (see the cross-file);
# fail here with a sentence rather than inside meson's compiler probe.
HOSTPY="$ROOT/deps/src/cpython/builddir/build/python3-native"
if [ ! -e "$HOSTPY" ]; then
    echo "!! $HOSTPY missing."
    echo "   numpy's code generators run on the HOST python, which is CPython's own build."
    echo "   Run build-cpython.sh first."
    exit 1
fi

rm -rf build-numpy
meson setup build-numpy "$NPY" --cross-file emscripten-crossfile.meson \
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
