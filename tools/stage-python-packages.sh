#!/usr/bin/env bash
# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) Virtastic
#
# Put the PYTHON half of every third-party package into deps/wasm/pyside-pkg, which the
# link preloads to /pyside-pkg.
#
#     bash tools/stage-python-packages.sh
#
# WHY THIS EXISTS
#
# The link statically registers the C extensions of numpy, matplotlib, Pillow, kiwisolver
# and IfcOpenShell in CPython's inittab, so `numpy._core._multiarray_umath` is a builtin
# module in the finished binary. None of that is reachable without the package it belongs
# to: `import numpy` runs numpy/__init__.py, and if that file is not on the virtual
# filesystem the import fails and every workbench that needs it is dead.
#
# That is exactly what shipped. The 2026-08-24 release carried three files in
# /pyside-pkg -- the PySide6, shiboken6 and pivy glue that patches/apply.sh copies -- while
# the 2026-08-13 release carried 1,850, including all of numpy, matplotlib, ifcopenshell,
# fontTools and PIL. Nothing in this repository ever created those 1,850 files: they were
# hand-placed on the build machine, survived in the runner's workspace, and vanished. FEM,
# Draft, BIM and Plot went with them, and every gate stayed green because Part and
# PartDesign need none of it.
#
# So the tree is built from things the repository controls: source trees the dependency
# lanes already fetch, and pinned pip downloads of the pure-Python libraries. Nothing here
# depends on what happens to be lying around in a directory.
#
# Rerunnable. It replaces what it stages and leaves the apply.sh glue alone.
set -euo pipefail
cd "$(dirname "$0")/.."

DEST="deps/wasm/pyside-pkg"
mkdir -p "$DEST"

missing=()
staged=()

# Copy a package directory out of a source tree the dependency lanes already fetch.
#   stage_dir <name> <path> [alternative path ...]
stage_dir() {
    local name="$1"; shift
    local src
    for src in "$@"; do
        if [ -d "$src" ]; then
            rm -rf "${DEST:?}/$name"
            cp -r "$src" "$DEST/$name"
            # .pyc for a different interpreter is dead weight in a 145 MB payload.
            find "$DEST/$name" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
            find "$DEST/$name" -name '*.pyc' -delete 2>/dev/null || true
            staged+=("$name <- $src")
            return 0
        fi
    done
    missing+=("$name (looked in: $*)")
    return 0
}

echo "== packages from the source trees the build already has"
# numpy keeps its Python package at the top of its source tree.
stage_dir numpy        deps/src/numpy/numpy
# matplotlib splits its Python across lib/.
stage_dir matplotlib   deps/src/matplotlib/lib/matplotlib
stage_dir mpl_toolkits deps/src/matplotlib/lib/mpl_toolkits
# Pillow's package is src/PIL.
stage_dir PIL          deps/src/Pillow/src/PIL deps/src/pillow/src/PIL
# IfcOpenShell ships its Python under src/ifcopenshell-python.
stage_dir ifcopenshell deps/src/IfcOpenShell/src/ifcopenshell-python/ifcopenshell \
                       deps/src/ifcopenshell/src/ifcopenshell-python/ifcopenshell

echo
echo "== pure-Python libraries, pinned"
# These have no compiled part, so a pinned wheel is the whole dependency. Versions are the
# ones matplotlib 3.9.2 and IfcOpenShell expect; bump them together, not one at a time.
PURE=(
    "fonttools==4.53.1"
    "packaging==24.1"
    "python-dateutil==2.9.0.post0"
    "pyparsing==3.1.4"
    "cycler==0.12.1"
    "six==1.16.0"
    "typing_extensions==4.12.2"
    "lark==1.2.2"
)
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
if python3 -m pip download --no-deps --dest "$TMP" "${PURE[@]}" >/dev/null 2>&1 \
   || python3 -m pip download --no-deps --dest "$TMP" "${PURE[@]}"; then
    python3 - "$TMP" "$DEST" <<'PY'
import sys, zipfile, pathlib, shutil
src, dest = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
for whl in sorted(src.glob('*.whl')):
    with zipfile.ZipFile(whl) as z:
        for member in z.namelist():
            top = member.split('/')[0]
            # Skip wheel metadata; keep the importable payload only.
            if top.endswith('.dist-info') or top.endswith('.data'):
                continue
            z.extract(member, dest)
    print('   %s' % whl.name)
PY
else
    missing+=("the pinned pure-Python wheels (pip download failed -- no network?)")
fi

echo
echo "== what is in $DEST now"
ls -1 "$DEST" | sed 's/^/   /'

# Verify against what a working release actually contained. A partial tree is the failure
# this script exists to prevent, so a missing package is an error, not a warning.
echo
echo "== verification"
REQUIRED=(numpy matplotlib mpl_toolkits PIL ifcopenshell fontTools packaging dateutil
          pyparsing cycler lark PySide6 shiboken6 pivy)
for pkg in "${REQUIRED[@]}"; do
    if [ -e "$DEST/$pkg/__init__.py" ] || [ -e "$DEST/$pkg.py" ]; then
        echo "  ok       $pkg"
    else
        missing+=("$pkg has no __init__.py in $DEST")
    fi
done

if [ ${#missing[@]} -gt 0 ]; then
    echo
    echo "::error::the staged Python tree is INCOMPLETE -- this is the defect that shipped"
    for m in "${missing[@]}"; do echo "::error::  $m"; done
    echo "A half-staged tree links the C extensions and then cannot import them." >&2
    exit 1
fi

echo
echo "staged $(find "$DEST" -type f | wc -l) files"
