#!/bin/bash
# Build the HOST shiboken6 generator -- the tool that reads Qt's headers and emits the C++
# binding sources the wasm shiboken then compiles.
#
# This is a prerequisite for rebuild-pyside-weh.sh, which passes it as
# QFP_SHIBOKEN_HOST_PATH and refuses to start without it. It has never been built anywhere
# but the build machine, where deps/host/shiboken6 simply already existed.
#
# The generator links against libclang: it parses Qt's headers with clang's C API rather
# than a hand-rolled parser. That is the only awkward dependency here, and it is the reason
# this lane was left for last.
#
# Usage: bash build-shiboken-host.sh
set -e
cd "$(dirname "$0")"
ROOT="$PWD"
SRC="$ROOT/deps/src/pyside-setup/sources/shiboken6"
BUILD="$ROOT/build-shiboken-host"
PREFIX="$ROOT/deps/host/shiboken6"

[ -d "$SRC" ] || { echo "!! $SRC missing -- fetch pyside-setup first" >&2; exit 1; }

if [ -f "$ROOT/.qtvenv/bin/activate" ]; then
    # shellcheck disable=SC1091
    source "$ROOT/.qtvenv/bin/activate"
fi

HOSTPY3="$(command -v python3 || command -v python)"
[ -n "$HOSTPY3" ] || { echo "!! no python3 on PATH" >&2; exit 1; }

# --- host Qt ---------------------------------------------------------------------------
QT_HOST=""
for d in "$ROOT/qt-host/6.9.0/gcc_64" "$ROOT/qt/6.9.0/macos" "$ROOT/qt/6.9.0/gcc_64" \
         "$ROOT/qt-host/6.9.0/macos"; do
    if [ -x "$d/bin/qmake" ] || [ -x "$d/bin/moc" ]; then QT_HOST="$d"; break; fi
done
[ -n "$QT_HOST" ] || { echo "!! no host Qt (need bin/qmake or bin/moc)" >&2; exit 1; }

# --- libclang --------------------------------------------------------------------------
# Report what is actually present before choosing, because the failure mode otherwise is a
# cmake error naming a variable rather than a missing package. Checked in order of
# preference: an explicit LLVM_INSTALL_DIR, a system llvm-config, the usual distro paths,
# and finally emsdk's own LLVM, which ships a complete clang.
echo "=== looking for libclang ==="
CAND=""
# stderr, not stdout: find_libclang's result is captured with $(...), so anything printed
# on stdout becomes part of the path. That produced
#   using libclang from:   /usr/lib/llvm-21   no libclang
report() { printf '  %-46s %s\n' "$1" "$2" >&2; }

if [ -n "${LLVM_INSTALL_DIR:-}" ] && [ -d "$LLVM_INSTALL_DIR" ]; then
    report "LLVM_INSTALL_DIR=$LLVM_INSTALL_DIR" "set"
    CAND="$LLVM_INSTALL_DIR"
fi

if [ -z "$CAND" ]; then
    for lc in llvm-config llvm-config-18 llvm-config-17 llvm-config-16 llvm-config-15 \
              llvm-config-14; do
        if command -v "$lc" >/dev/null 2>&1; then
            p="$("$lc" --prefix 2>/dev/null || true)"
            report "$lc" "${p:-(no --prefix)}"
            if [ -n "$p" ] && ls "$p"/lib/libclang.so* "$p"/lib/libclang.dylib >/dev/null 2>&1; then
                CAND="$p"; break
            fi
        fi
    done
fi

# Glob rather than enumerate versions. An earlier hardcoded list stopped at llvm-18, so
# when apt installed llvm-21 the search missed it and fell through to downloading a 700 MB
# tarball that then would not link. Newest first.
llvm_prefixes() {
    # shellcheck disable=SC2012
    ls -d /usr/lib/llvm-* /usr/local/lib/llvm-* 2>/dev/null \
        | sed 's/.*llvm-//' | sort -rn | sed 's#^#/usr/lib/llvm-#'
    echo /usr
    echo /usr/local
    echo "$ROOT/emsdk/upstream"
}

# Require BOTH the library and ClangConfig.cmake from the SAME prefix.
#
# Two reasons. Shiboken needs the cmake package anyway -- find_package(Clang) -- so a
# prefix with only the .so is no use. And more importantly the generator resolves clang's
# builtin headers AT RUNTIME from whatever clang it finds: a generator linked against
# libclang 17 while picking up llvm-21's builtins parses nothing and reports
#
#   qt.shiboken: (shiboken) No C++ classes found!
#
# which looks like a typesystem problem and is really a version mismatch. Insisting on one
# self-consistent prefix rules that out.
#
# Ubuntu also names the library libclang-21.so.21.1 rather than libclang.so.21, so match
# libclang*.so* -- an earlier libclang.so* glob missed apt's install entirely.
find_libclang() {
    local d
    while IFS= read -r d; do
        [ -d "$d" ] || continue
        local haslib="" hascmake=""
        ls "$d"/lib/libclang*.so* "$d"/lib/libclang.dylib \
           "$d"/lib/x86_64-linux-gnu/libclang*.so* >/dev/null 2>&1 && haslib=1
        [ -f "$d/lib/cmake/clang/ClangConfig.cmake" ] && hascmake=1
        if [ -n "$haslib" ] && [ -n "$hascmake" ]; then
            report "$d" "libclang + ClangConfig.cmake"
            printf '%s\n' "$d"
            return 0
        fi
        report "$d" "lib=${haslib:-no} cmake=${hascmake:-no}"
    done < <(llvm_prefixes)
    return 1
}

if [ -z "$CAND" ]; then
    CAND="$(find_libclang || true)"
fi

# Nothing installed. Try the distro first (cheapest, and correct if it works), then fall
# back to an LLVM release tarball. Qt publishes prebuilt libclang for exactly this purpose
# but only as .7z, which needs p7zip; LLVM's own releases are plain .tar.xz and contain the
# same thing.
if [ -z "$CAND" ] && [ "${FCWEB_NO_LIBCLANG_FETCH:-0}" != "1" ]; then
    if sudo -n true 2>/dev/null; then
        echo "  trying: sudo apt-get install libclang-dev llvm-dev"
        if sudo -n apt-get update -qq && sudo -n apt-get install -y -qq libclang-dev llvm-dev; then
            # Same globbing search, not a second hardcoded list: apt installed llvm-21
            # here, and a list stopping at llvm-18 missed it entirely.
            CAND="$(find_libclang || true)"
            [ -n "$CAND" ] && report "apt" "installed -> $CAND"
        fi
    else
        echo "  no passwordless sudo; skipping apt"
    fi
fi

if [ -z "$CAND" ] && [ "${FCWEB_NO_LIBCLANG_FETCH:-0}" != "1" ]; then
    LLVM_VER="${FCWEB_LLVM_VERSION:-20.1.8}"
    # LLVM-<ver>-Linux-X64 rather than a clang+llvm-*-ubuntu-* asset: the ubuntu-18.04
    # builds want libtinfo.so.5 and fail with
    #   undefined reference to setupterm@NCURSES_TINFO_5.0.19991023
    # The version MATTERS: libclang must be able to parse emsdk's sysroot, which is
    # clang 20. libclang 17 against a clang-20 libc++ gives
    #   <cstddef> tried including <stddef.h> but did not find libc++'s <stddef.h>
    # no matter which resource dir it is handed.
    LLVM_TARBALL="LLVM-${LLVM_VER}-Linux-X64.tar.xz"
    LLVM_DIR="$ROOT/deps/host/llvm-${LLVM_VER}"
    if [ ! -e "$LLVM_DIR/lib/libclang.so" ] && ! ls "$LLVM_DIR"/lib/libclang.so* >/dev/null 2>&1; then
        echo "  fetching LLVM ${LLVM_VER} (for libclang only; ~700 MB, cached afterwards)"
        mkdir -p "$LLVM_DIR"
        if curl -fL --retry 3 -o /tmp/llvm.tar.xz \
             "https://github.com/llvm/llvm-project/releases/download/llvmorg-${LLVM_VER}/${LLVM_TARBALL}"; then
            tar xf /tmp/llvm.tar.xz -C "$LLVM_DIR" --strip-components=1
            rm -f /tmp/llvm.tar.xz
        else
            echo "  !! LLVM ${LLVM_VER} download failed" >&2
        fi
    fi
    if ls "$LLVM_DIR"/lib/libclang.so* >/dev/null 2>&1; then
        report "$LLVM_DIR" "has libclang"
        CAND="$LLVM_DIR"
    fi
fi

if [ -z "$CAND" ]; then
    cat >&2 <<'EOF'

!! No libclang found anywhere this script knows to look.

   The shiboken GENERATOR parses Qt's headers with clang's C API, so it cannot be
   built without it. Options, cheapest first:

     sudo apt-get install -y libclang-dev llvm-dev     # if this box has sudo

     or set LLVM_INSTALL_DIR to a prefix containing lib/libclang.so, e.g. one of
     Qt's prebuilt tarballs from
     https://download.qt.io/development_releases/prebuilt/libclang/

   Nothing else in this build needs libclang -- only this generator.
EOF
    exit 1
fi

echo "using libclang from: $CAND"
export LLVM_INSTALL_DIR="$CAND"
export CLANG_INSTALL_DIR="$CAND"

# --- configure and build -----------------------------------------------------------------
rm -rf "$BUILD"
# shiboken does find_package(Clang), which wants ClangConfig.cmake from the LLVM
# DEVELOPMENT package -- having libclang.so is not enough:
#   Could not find a package configuration file provided by "Clang"
CLANG_CMAKE=""
LLVM_CMAKE=""
for d in "$CAND" /usr/lib/llvm-*; do
    [ -d "$d" ] || continue
    if [ -z "$CLANG_CMAKE" ] && [ -f "$d/lib/cmake/clang/ClangConfig.cmake" ]; then
        CLANG_CMAKE="$d/lib/cmake/clang"
    fi
    if [ -z "$LLVM_CMAKE" ] && [ -f "$d/lib/cmake/llvm/LLVMConfig.cmake" ]; then
        LLVM_CMAKE="$d/lib/cmake/llvm"
    fi
done
if [ -z "$CLANG_CMAKE" ]; then
    echo "!! no ClangConfig.cmake anywhere. libclang.so alone is not enough -- shiboken" >&2
    echo "   calls find_package(Clang). Install the dev package (libclang-<n>-dev)." >&2
    ls -d /usr/lib/llvm-*/lib/cmake/* 2>/dev/null | sed 's/^/     /' | head >&2
    exit 1
fi
echo "clang cmake:  $CLANG_CMAKE"
[ -n "$LLVM_CMAKE" ] && echo "llvm cmake:   $LLVM_CMAKE"

cmake -S "$SRC" -B "$BUILD" -G Ninja \
  -DCMAKE_POLICY_VERSION_MINIMUM=3.5 \
  -DCMAKE_BUILD_TYPE=Release \
  -DClang_DIR="$CLANG_CMAKE" \
  ${LLVM_CMAKE:+-DLLVM_DIR="$LLVM_CMAKE"} \
  -DCMAKE_PREFIX_PATH="$QT_HOST;$CAND" \
  -DQt6_DIR="$QT_HOST/lib/cmake/Qt6" \
  -DPython_EXECUTABLE="$HOSTPY3" \
  -DCMAKE_INSTALL_PREFIX="$PREFIX"

ninja -C "$BUILD" install

# The whole point of this script is one executable. Check for it by name rather than
# trusting ninja, since a partial install here surfaces much later as a cmake error in
# rebuild-pyside-weh.sh about QFP_SHIBOKEN_HOST_PATH.
GEN=""
for c in "$PREFIX/bin/shiboken6" "$PREFIX/bin/shiboken6.exe"; do
    [ -x "$c" ] && { GEN="$c"; break; }
done
if [ -z "$GEN" ]; then
    echo "!! no shiboken6 generator under $PREFIX/bin. What was installed:" >&2
    find "$PREFIX" -maxdepth 3 -type f | sed 's/^/     /' | head -20 >&2
    exit 1
fi
# Record which LLVM this generator was built against. It resolves clang's builtin headers
# at RUN time, and it runs from rebuild-pyside-weh.sh, where LLVM_INSTALL_DIR is not set --
# so it fell back to a default search, found a different LLVM, and parsed nothing:
#   CLANG v0.64, builtins includes directory: /usr/lib/llvm-21/lib/clang/21/include
#   No C++ classes found!
# Writing it here means the consumer cannot guess wrong.
printf '%s\n' "$CAND" > "$PREFIX/.llvm-prefix"
echo "llvm prefix recorded: $PREFIX/.llvm-prefix -> $CAND"

echo "host shiboken: $GEN"
"$GEN" --version 2>&1 | sed 's/^/  /' || true
