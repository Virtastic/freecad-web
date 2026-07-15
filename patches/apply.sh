#!/usr/bin/env bash
# Apply every stored source patch onto pristine vendored deps/ checkouts, then copy the
# hand-authored PySide package glue into place. Run once after cloning the deps/ trees at
# their pinned commits and before configuring/building. Safe to re-run: each patch is
# checked first and skipped if already applied. See README.md for versions/regenerable bits.
set -euo pipefail
cd "$(dirname "$0")/.."          # repo root
PATCHES="$PWD/patches"

apply_one() {
  local tree="deps/src/$1" patch="$PATCHES/$2"
  [ -d "$tree/.git" ] || { echo "  !! $1: missing checkout $tree — clone it first"; return 1; }
  [ -f "$patch" ] || { echo "  !! $1: missing $patch"; return 1; }
  if git -C "$tree" apply --reverse --check "$patch" 2>/dev/null; then
    echo "  == $1: already applied (skip)"
  elif git -C "$tree" apply --check "$patch" 2>/dev/null; then
    git -C "$tree" apply "$patch"; echo "  ++ $1: applied ${2}"
  else
    echo "  !! $1: $2 does NOT apply cleanly — tree may be at the wrong commit"; return 1
  fi
}

echo "Applying source patches:"
apply_one freecad       freecad.patch
apply_one pyside-setup  pyside-setup.patch
apply_one occt          occt.patch
apply_one cpython       cpython-ctypes-wasm.patch
apply_one numpy         numpy.patch
apply_one coin3d        coin3d.patch

echo "Copying PySide package glue (deps/wasm must already exist):"
if [ -d deps/wasm/pyside-pkg ]; then
  cp -v patches/pyside-pkg-glue/PySide6/__init__.py           deps/wasm/pyside-pkg/PySide6/__init__.py
  cp -v patches/pyside-pkg-glue/shiboken6/__init__.py         deps/wasm/pyside-pkg/shiboken6/__init__.py
  cp -v patches/pyside-pkg-glue/pivy/__init__.py              deps/wasm/pyside-pkg/pivy/__init__.py
  cp -v patches/pyside-pkg-glue/include-shiboken/sbkversion.h deps/wasm/include/shiboken/sbkversion.h
else
  echo "  (deps/wasm/pyside-pkg not present yet — copy glue after the pyside/pivy build; see README.md)"
fi
echo "done."
