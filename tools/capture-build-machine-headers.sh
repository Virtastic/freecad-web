#!/usr/bin/env bash
# Capture the hand-written headers that exist only on the build machine.
#
# WHY THIS EXISTS
#
# tools/capture-dep-versions.sh captures WHICH SOURCES the release was built from. This
# captures the sources that were never in deps/src at all: files written by hand into
# deps/wasm/include, which is gitignored.
#
# Three of them are force-included into everything -- Coin3D, all of FreeCAD (C and C++),
# PySide, and all three link commands:
#
#     gl_compat.h        legacy fixed-function GL declarations for a GLES/WebGL2 target
#     coin_intrusive.h   boost::intrusive_ptr adapters for SoBase
#     qprocess_stub.h    inert QProcess for Qt-for-WebAssembly, which has no subprocesses
#                        (src/Gui/CMakeLists.txt force-includes it into all of FreeCADGui)
#
# Ten tracked files consume them; nothing in the repository produces them. So a clean
# checkout cannot build FreeCAD, and could not have at any point in this project's history.
# It is the CalculiX defect again -- uncaptured build-machine state, invisible because the
# path is gitignored -- and it is the last thing standing between this repository and a
# reproducible build.
#
# HOW TO USE IT
#
#     bash tools/capture-build-machine-headers.sh
#     git add toolchain/include && git commit -m "capture the force-included compat headers"
#
# Run it ON THE BUILD MACHINE, from the repo root, with deps/wasm/include populated as it
# was for the release. It only reads deps/ and writes into toolchain/include/.
#
# It deliberately captures ONLY hand-written headers. Anything a dependency's `make install`
# put there belongs to that dependency and is reproduced by rebuilding it, not by copying.
set -uo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"

DW="${DW:-$root/deps/wasm}"
dest="$root/toolchain/include"

if [ ! -d "$DW/include" ]; then
  echo "ERROR: no $DW/include here. Run this on the build machine, from the repo root." >&2
  exit 1
fi

mkdir -p "$dest"

# The known force-includes, plus anything else that looks hand-written rather than installed.
# Add to this list rather than widening the glob: a blanket copy would sweep in thousands of
# OCCT/VTK/boost headers that are already reproduced by their own builds.
WANTED="gl_compat.h coin_intrusive.h qprocess_stub.h"

captured=0
for name in $WANTED; do
  src="$DW/include/$name"
  if [ ! -e "$src" ]; then
    echo "  $name: NOT PRESENT on this machine"
    continue
  fi
  if [ -e "$dest/$name" ] && cmp -s "$src" "$dest/$name"; then
    echo "  $name: unchanged ($(wc -l < "$src" | tr -d ' ') lines)"
    continue
  fi
  if [ -e "$dest/$name" ]; then
    echo "  $name: DIFFERS from the tracked copy -- overwriting with the build machine's."
    diff -u "$dest/$name" "$src" | sed 's/^/    | /' | head -60
  else
    echo "  $name: captured ($(wc -l < "$src" | tr -d ' ') lines)"
  fi
  cp "$src" "$dest/$name"
  captured=$((captured + 1))
done

echo
echo "--- other headers in $DW/include that no dependency installed ---"
echo "(review these by hand; if one is hand-written, add it to WANTED above)"
for f in "$DW/include"/*.h; do
  [ -e "$f" ] || continue
  n="$(basename "$f")"
  case " $WANTED " in *" $n "*) continue ;; esac
  # Installed headers are almost always > 40 lines and carry an upstream copyright.
  if ! grep -qiE 'copyright|SPDX' "$f" 2>/dev/null; then
    printf '  %-32s %5s lines  (no copyright header -- possibly hand-written)\n' \
      "$n" "$(wc -l < "$f" | tr -d ' ')"
  fi
done

echo
if [ "$captured" -gt 0 ]; then
  echo "Captured $captured header(s) into toolchain/include/. Commit them:"
  echo "    git add toolchain/include && git commit"
else
  echo "Nothing new captured."
fi
