#!/usr/bin/env bash
# Apply every stored source patch onto pristine vendored deps/ checkouts, then copy the
# hand-authored PySide package glue into place. Run once after cloning the deps/ trees at
# their pinned commits and before configuring/building. Safe to re-run: each patch is
# checked first and skipped if already applied. See README.md for versions/regenerable bits.
set -euo pipefail
cd "$(dirname "$0")/.."          # repo root
PATCHES="$PWD/patches"

# A tree may be a git checkout (the build machine clones them) or a plain tarball extract
# (CI fetches release tarballs, because cloning OCCT/CPython/FreeCAD to build one commit is
# minutes of transfer for nothing). This used to REQUIRE .git and bail otherwise, which is
# why no patch in this directory has ever been applied in CI -- including freecad.patch,
# without which there is no point building FreeCAD at all. Both layouts are handled now:
# git apply where there is an index to be careful about, plain patch(1) where there is not.
apply_one() {
  local tree="deps/src/$1" patch="$PATCHES/$2"
  if [ ! -d "$tree" ]; then
    # CI builds a subset of the stack, so "tree absent" is normal there and fatal here.
    # Default stays strict: on the build machine a missing tree means the build you are
    # about to start is not the build you think it is.
    if [ "${FCWEB_PATCH_OPTIONAL:-0}" = "1" ]; then
      echo "  -- $1: tree absent, skipping (FCWEB_PATCH_OPTIONAL=1)"; return 0
    fi
    echo "  !! $1: missing tree $tree — clone or fetch it first"; return 1
  fi
  # An empty patch is legitimate: the repo is registered (so regen.sh keeps capturing any
  # future fix) but currently carries no local changes.
  [ -s "$patch" ] || { echo "  == $1: no local changes to apply"; return 0; }

  if [ -d "$tree/.git" ]; then
    if git -C "$tree" apply --reverse --check "$patch" 2>/dev/null; then
      echo "  == $1: already applied (skip)"
    elif git -C "$tree" apply --check "$patch" 2>/dev/null; then
      git -C "$tree" apply "$patch"; echo "  ++ $1: applied ${2}"
    else
      echo "  !! $1: $2 does NOT apply cleanly — tree may be at the wrong commit"; return 1
    fi
    return 0
  fi

  # Tarball extract. patch(1) rather than `git apply`, deliberately: inside this repository's
  # own work tree git would resolve the enclosing .git and bring index semantics to a
  # directory that has nothing to do with it. -R --dry-run first, so re-running is a no-op.
  if patch -d "$tree" -p1 -R --dry-run --force --silent < "$patch" >/dev/null 2>&1; then
    echo "  == $1: already applied (skip, tarball)"
  elif patch -d "$tree" -p1 --dry-run --force --silent < "$patch" >/dev/null 2>&1; then
    patch -d "$tree" -p1 --silent < "$patch"; echo "  ++ $1: applied ${2} (tarball)"
  else
    echo "  !! $1: $2 does NOT apply cleanly — tree may be at the wrong version"; return 1
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
