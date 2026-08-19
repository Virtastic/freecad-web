#!/bin/bash
# Build libffi (pyodide's wasm-capable fork) + CPython _ctypes for wasm.
# Enables the `ctypes` stdlib module (and thus matplotlib's interactive QtAgg
# canvas). libffi creates function-table entries at runtime for closures, so the
# final FreeCAD link needs -sALLOW_TABLE_GROWTH (added in configure-gui.sh).
set -e
cd "$(dirname "$0")"
ROOT="$PWD"; DW="$ROOT/deps/wasm"
source emsdk/emsdk_env.sh >/dev/null 2>&1

# 1. libffi (needs automake for autogen)
if [ ! -d deps/src/libffi ]; then
  git clone --depth 1 https://github.com/hoodmane/libffi-emscripten.git deps/src/libffi
fi
cd deps/src/libffi
# libtoolize BEFORE autogen. libffi's configure.ac uses LT_SYS_SYMBOL_USCORE, which lives
# in libtool.m4, and aclocal only sees it once libtoolize has copied the libtool macros
# into m4/. Having the libtool package installed is not enough -- autoreconf stops with
#   configure.ac:219: error: possibly undefined macro: LT_SYS_SYMBOL_USCORE
# which reads like a missing package when it is really a missing step.
if [ ! -f configure ]; then
  # ACLOCAL_PATH so aclocal can see libtool.m4 wherever the distro put it. libtoolize
  # --install copies the macros into m4/, but autogen.sh re-runs autoreconf which
  # invokes plain `libtoolize --copy` and aclocal -I m4; if the copy did not land,
  # LT_SYS_SYMBOL_USCORE is undefined again. Giving aclocal the system macro directory
  # makes it work either way.
  for d in /usr/share/aclocal /usr/local/share/aclocal; do
    [ -d "$d" ] && ACLOCAL_PATH="${ACLOCAL_PATH:+$ACLOCAL_PATH:}$d"
  done
  export ACLOCAL_PATH
  echo "ACLOCAL_PATH=$ACLOCAL_PATH"
  # The fork ships its own m4/, and `aclocal -I m4` searches that FIRST. If those copies
  # predate LT_SYS_SYMBOL_USCORE, the system libtool.m4 never gets a look in and autoreconf
  # fails no matter what ACLOCAL_PATH says. So refresh them, then CHECK -- and if the macro
  # is still missing, copy the system libtool.m4 in directly rather than failing with a
  # message that blames a package which is installed.
  if command -v libtoolize >/dev/null 2>&1; then
    libtoolize --copy --install --force || libtoolize --copy --force || true
  fi
  if ! grep -rqs 'LT_SYS_SYMBOL_USCORE' m4/ 2>/dev/null; then
    for d in /usr/share/aclocal /usr/local/share/aclocal; do
      if grep -qs 'AC_DEFUN(\[LT_SYS_SYMBOL_USCORE\]' "$d/libtool.m4" 2>/dev/null; then
        mkdir -p m4 && cp "$d/libtool.m4" m4/
        echo "copied $d/libtool.m4 into m4/ (defines LT_SYS_SYMBOL_USCORE)"
        break
      fi
    done
  fi
  # Still absent after libtoolize copied m4/libtool.m4: this libtool release simply does
  # not ship LT_SYS_SYMBOL_USCORE. Supply it. The macro exists to discover whether the
  # toolchain prefixes C symbols with an underscore, and for wasm32-emscripten the answer
  # is a fact rather than something to probe: it does not. libffi only reads
  # $sys_symbol_underscore afterwards, so a minimal definition is faithful, not a fudge.
  if ! grep -rqs 'LT_SYS_SYMBOL_USCORE' m4/ 2>/dev/null; then
    mkdir -p m4
    cat > m4/lt_sys_symbol_uscore.m4 <<'M4EOF'
# Supplied by freecad-web: this libtool does not ship LT_SYS_SYMBOL_USCORE.
# wasm32-emscripten does not prefix C symbols with an underscore.
AC_DEFUN([LT_SYS_SYMBOL_USCORE],
[AC_CACHE_CHECK([for _ prefix in compiled symbols],
   [lt_cv_sys_symbol_underscore],
   [lt_cv_sys_symbol_underscore=no])
 sys_symbol_underscore=$lt_cv_sys_symbol_underscore
])
M4EOF
    echo "supplied m4/lt_sys_symbol_uscore.m4 (no underscore prefix on wasm32-emscripten)"
  fi
  if ! grep -rqs 'LT_SYS_SYMBOL_USCORE' m4/ 2>/dev/null; then
    echo "!! LT_SYS_SYMBOL_USCORE is defined nowhere reachable:"
    echo "   libtoolize: $(command -v libtoolize || echo absent)"
    echo "   libtool:    $(libtool --version 2>/dev/null | head -1 || echo absent)"
    grep -rls 'LT_SYS_SYMBOL_USCORE' /usr/share/aclocal /usr/local/share/aclocal 2>/dev/null       | sed 's/^/   defines it: /' | head
    ls m4/ 2>/dev/null | sed 's/^/   m4\/: /' | head
  fi
  ./autogen.sh
fi
emconfigure ./configure --host=wasm32-unknown-emscripten --enable-static --disable-shared \
  --disable-dependency-tracking CFLAGS="-fPIC -O2 -fexceptions -pthread"
emmake make -j4 libffi.la   # 'make' fails on docs (texinfo); build just the lib
FFI="$PWD/wasm32-unknown-emscripten"
cp "$FFI/.libs/libffi.a" "$DW/lib/libffi.a"
cp "$FFI/include/ffi.h" "$FFI/include/ffitarget.h" "$DW/include/"
cd "$ROOT"

# 2. CPython _ctypes module against libffi
CT="$ROOT/deps/src/cpython/Modules/_ctypes"
OUT=/tmp/ctbuild; mkdir -p "$OUT"; rm -f "$OUT"/*.o
FLAGS=(-c -O2 -fexceptions -pthread -fPIC
  -DHAVE_FFI_PREP_CIF_VAR -DHAVE_FFI_PREP_CLOSURE_LOC -DHAVE_FFI_CLOSURE_ALLOC -DPy_BUILD_CORE_MODULE
  -I"$DW/include" -I"$ROOT/deps/src/cpython/Include" -I"$ROOT/deps/src/cpython/builddir/emscripten-mt"
  -I"$ROOT/deps/src/cpython/Include/internal" -I"$CT")
for src in _ctypes callbacks callproc stgdict cfield malloc_closure; do
  emcc "${FLAGS[@]}" "$CT/$src.c" -o "$OUT/$src.o"
done
mkdir -p "$DW/lib/ctypes-mod"
"$ROOT/emsdk/upstream/emscripten/emar" rcs "$DW/lib/ctypes-mod/lib_ctypes.a" "$OUT"/*.o
echo "_ctypes built (PyInit__ctypes):"
"$ROOT/emsdk/upstream/emscripten/emnm" "$DW/lib/ctypes-mod/lib_ctypes.a" | grep 'T PyInit'
