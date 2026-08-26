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
            # .pyc for a different interpreter is dead weight in a payload every visitor
            # downloads.
            find "$DEST/$name" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
            find "$DEST/$name" -name '*.pyc' -delete 2>/dev/null || true
            # Test suites too. numpy alone ships thousands of test files, and staging from a
            # source tree takes the lot -- the working release carried 325 numpy files, a
            # raw copy is several times that, and every one of them is bytes a user waits
            # for on first load. Directories named `tests` only: numpy.testing is a public
            # API that numpy itself imports, and dropping it would break the package.
            find "$DEST/$name" -type d -name 'tests' -prune -exec rm -rf {} + 2>/dev/null || true
            find "$DEST/$name" -type d -name 'test' -prune -exec rm -rf {} + 2>/dev/null || true
            # And the C sources. Staging from a source tree brings numpy's .c/.h/.s
            # along -- 21 MB of a 226 MB payload for files that cannot be used: there
            # is no compiler in the browser, so headers for building extensions and
            # the assembly kernels' sources are pure download.
            #
            # Deliberately NOT pruned by extension alone: ifcopenshell's .ifc files are
            # property-set SCHEMAS it reads at runtime, and the .stp under Mod/Idf is the
            # IDF workbench's component library. Both look like test data and are not.
            for ext in c h hpp cpp cc s S pyx pxd pyi in f f90 m4; do
                find "$DEST/$name" -type f -name "*.$ext" -delete 2>/dev/null || true
            done
            # ... and the rest of that same tree. Pruning by extension left 4.79 MB of
            # numpy/_core/src behind in 146 files -- .src templates, .md, .ipynb, and a
            # 2.5 MB PDF of the highway library's design notes. It is numpy's C SOURCE
            # directory: build input, never imported, and there is no compiler here to
            # use it. Measured from the shipped payload, not guessed.
            #
            # Scoped to this one directory rather than a global doc sweep, because the
            # things that LOOK like docs elsewhere are runtime data: ifcopenshell's .ifc
            # property-set schemas, matplotlib's .ttf and .afm font metrics, and the .stp
            # component library under Mod/Idf.
            rm -rf "$DEST/$name/_core/src" 2>/dev/null || true
            # Documentation that no runtime reads, wherever a package puts it. Kept to
            # formats that are unambiguously prose: a .pdf or a notebook is never data
            # the application opens.
            find "$DEST/$name" -type f -name '*.ipynb' -delete 2>/dev/null || true
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
# pivy's Python package. Its __init__.py is replaced by the glue below, which points
# pivy.coin at the statically linked _coin rather than at a shared library.
stage_dir pivy         deps/src/pivy/pivy
# matplotlib imports kiwisolver for its layout solver, and only the C half of that
# is linked in -- the package itself was never staged, so matplotlib died with
# "No module named 'kiwisolver'" once its own files were finally in place.
stage_dir kiwisolver   deps/src/kiwisolver/py/kiwisolver deps/src/kiwi/py/kiwisolver


echo
echo "== the GENERATED python each package needs (not in its source tree)"
# Staging a source tree gets the hand-written half of a package. Three of these are not
# importable without files their own build produces, and each failed in a different and
# initially confusing way:
#
#   numpy          __config__.py is generated from __config__.py.in. Without it numpy's
#                  __init__ raises "you should not try to import numpy from its source
#                  directory", which reads like a path problem and is actually a missing
#                  generated file.
#   pivy           coin.py is written by SWIG at build time; the source tree has none, so
#                  `from .coin import SoDB` fails with No module named 'pivy.coin'.
#   ifcopenshell   ifcopenshell_wrapper.py is SWIG's shim over the compiled extension.
#                  Its absence is reported as "IfcOpenShell not built for
#                  'emscripten/32bit/python3.13'", which sounds like a platform problem.
#
# Each is copied from the build directory the lane already produces, and a miss is an
# error: a package that imports on the build machine and not in the browser is exactly
# the failure this script exists to stop.

# find_one <description> <destination> <search-root> <filename>
find_one() {
    local what="$1" dest="$2" root="$3" fname="$4"
    if [ ! -d "$root" ]; then
        missing+=("$what: no $root -- has that lane run?")
        return 0
    fi
    local hit
    hit="$(find "$root" -name "$fname" -type f 2>/dev/null | head -1)"
    if [ -z "$hit" ]; then
        missing+=("$what: no $fname anywhere under $root")
        return 0
    fi
    cp "$hit" "$dest"
    echo "   $what <- $hit"
}

[ -d "$DEST/numpy" ] && find_one "numpy/__config__.py" "$DEST/numpy/__config__.py" \
    build-numpy "__config__.py"
# The .in template only confuses a reader once the real file is beside it.
rm -f "$DEST/numpy/__config__.py.in" 2>/dev/null || true

[ -d "$DEST/pivy" ] && find_one "pivy/coin.py" "$DEST/pivy/coin.py" \
    build-pivy-wasm "coin.py"

[ -d "$DEST/ifcopenshell" ] && find_one "ifcopenshell/ifcopenshell_wrapper.py" \
    "$DEST/ifcopenshell/ifcopenshell_wrapper.py" build-ifcopenshell "ifcopenshell_wrapper.py"

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
echo "== two packages that need a little more than their files"
python3 - "$DEST" <<'PYEOF'
import io
import os
import sys

dest = sys.argv[1]

# --- matplotlib: _version.py is generated by setuptools-scm at build time, exactly like
# numpy's __config__.py. Without it matplotlib's __init__ dies on
#   cannot import name '_version' from partially initialized module 'matplotlib'
# which reads like a circular import and is a missing file. The version is pinned by the
# build (PYDEPS_KEY names mpl3.9.2), so it can be written rather than hunted for.
MPL_VERSION = "3.9.2"
mpl = os.path.join(dest, "matplotlib")
if os.path.isdir(mpl):
    p = os.path.join(mpl, "_version.py")
    if not os.path.exists(p):
        tup = ", ".join(MPL_VERSION.split("."))
        io.open(p, "w", encoding="utf-8", newline="").write(
            "# Generated by the build for the wasm payload: setuptools-scm writes this file\n"
            "# during a normal install, and staging from a source tree does not get one.\n"
            "__version__ = version = '%s'\n"
            "__version_tuple__ = version_tuple = (%s)\n" % (MPL_VERSION, tup))
        print("   wrote matplotlib/_version.py (%s)" % MPL_VERSION)

# --- ifcopenshell: its SWIG wrapper does `from . import _ifcopenshell_wrapper`, but the
# extension is registered in the inittab under the BARE name, so the relative import
# fails and __init__ turns that into "IfcOpenShell not built for
# 'emscripten/32bit/python3.13'" -- a message about the platform for what is really a
# module-naming mismatch. Alias the builtin into the package before the wrapper looks for
# it. This is the same trick patches/pyside-pkg-glue/pivy/__init__.py uses for _coin.
ifc = os.path.join(dest, "ifcopenshell", "__init__.py")
PROLOGUE = (
    "# FCWEB: the compiled wrapper is a BUILTIN under its bare name, because the inittab is\n"
    "# fixed at link time and has no notion of packages. Alias it in before the SWIG shim\n"
    "# below does `from . import _ifcopenshell_wrapper`, which would otherwise fail and be\n"
    "# reported as 'IfcOpenShell not built for this platform'.\n"
    "import sys as _fcweb_sys\n"
    "import importlib as _fcweb_il\n"
    "try:\n"
    "    _fcweb_sys.modules[__name__ + '._ifcopenshell_wrapper'] = "
    "_fcweb_il.import_module('_ifcopenshell_wrapper')\n"
    "except Exception:\n"
    "    pass\n"
)
if os.path.exists(ifc):
    src = io.open(ifc, encoding="utf-8", errors="replace").read()
    if "_fcweb_il.import_module" not in src:
        # AFTER any __future__ imports. Putting it at the very top produced
        #   SyntaxError: from __future__ imports must occur at the beginning of the file
        # because ifcopenshell has one at line 66 -- and a package that will not parse
        # is worse than the naming mismatch this is here to fix.
        lines = src.split(chr(10))
        at = 0
        for i, line in enumerate(lines):
            if line.startswith("from __future__ import"):
                at = i + 1
        out = chr(10).join(lines[:at]) + (chr(10) if at else "") + PROLOGUE + \
            chr(10).join(lines[at:])
        import ast as _ast
        _ast.parse(out)          # never write a file this script has just broken
        io.open(ifc, "w", encoding="utf-8", newline="").write(out)
        print("   aliased the ifcopenshell wrapper builtin into the package "
              "(after %d __future__ line(s))" % at)
PYEOF

echo
echo "== does every staged file actually parse?"
# A payload can be complete and still broken. matplotlib shipped an IndentationError for
# who knows how long because this repository's own PIL guard was applied twice to a cached
# source tree, and nothing between that edit and the browser ever compiled the result.
#
# The lane that owns the fix cannot be relied on to run -- it skips when its archive is
# already built, which is exactly the case on a machine that keeps its state. So the check
# lives here, where the bytes are actually chosen, and repairs what it can from the pinned
# upstream tag rather than only complaining.
python3 - "$DEST" <<'PYEOF'
import ast
import io
import os
import sys
import urllib.request

dest = sys.argv[1]

# package -> how to fetch a pristine copy of one of its files, pinned to the version built
PINNED = {
    'matplotlib': 'https://raw.githubusercontent.com/matplotlib/matplotlib/v3.9.2/lib/matplotlib/%s',
    'numpy': 'https://raw.githubusercontent.com/numpy/numpy/v2.1.3/numpy/%s',
}

bad = []
healed = 0
checked = 0
for root, dirs, files in os.walk(dest):
    dirs[:] = [d for d in dirs if d != '__pycache__']
    for fn in files:
        if not fn.endswith('.py'):
            continue
        p = os.path.join(root, fn)
        checked += 1
        try:
            src = io.open(p, encoding='utf-8', errors='replace').read()
            ast.parse(src)
            continue
        except SyntaxError as exc:
            rel = os.path.relpath(p, dest).replace(os.sep, '/')
            pkg = rel.split('/')[0]
            url = PINNED.get(pkg)
            if not url:
                bad.append('%s: %s' % (rel, exc.msg))
                continue
            inner = rel.split('/', 1)[1]
            try:
                fresh = urllib.request.urlopen(url % inner, timeout=60).read().decode('utf-8')
                ast.parse(fresh)
            except Exception as e2:
                bad.append('%s: %s (and re-fetch failed: %s)' % (rel, exc.msg, e2))
                continue
            io.open(p, 'w', encoding='utf-8', newline='').write(fresh)
            healed += 1
            print('   healed %s (was: %s)' % (rel, exc.msg))

print('   %d python files checked, %d healed' % (checked, healed))
if bad:
    print('::error::%d staged file(s) do not parse and could not be repaired' % len(bad))
    for b in bad[:10]:
        print('::error::  %s' % b)
    raise SystemExit(1)
PYEOF

echo
echo "== re-apply the glue, last"
# apply.sh copies these, but it runs BEFORE this script and staging pivy from source would
# overwrite pivy/__init__.py with the upstream one -- which looks for a shared library that
# does not exist in a static build. Copying them last makes this script correct whatever
# order it runs in, rather than correct by luck.
mkdir -p "$DEST/PySide6" "$DEST/shiboken6" "$DEST/pivy"
for pair in "PySide6/__init__.py" "shiboken6/__init__.py" "pivy/__init__.py"; do
    if [ -f "patches/pyside-pkg-glue/$pair" ]; then
        cp "patches/pyside-pkg-glue/$pair" "$DEST/$pair"
        echo "   $pair"
    else
        missing+=("glue patches/pyside-pkg-glue/$pair")
    fi
done

echo
echo "== what is in $DEST now"
ls -1 "$DEST" | sed 's/^/   /'

# Verify against what a working release actually contained. A partial tree is the failure
# this script exists to prevent, so a missing package is an error, not a warning.
echo
echo "== verification"
REQUIRED=(numpy matplotlib mpl_toolkits PIL ifcopenshell kiwisolver fontTools packaging dateutil
          pyparsing cycler lark PySide6 shiboken6 pivy)
for pkg in "${REQUIRED[@]}"; do
    if [ -e "$DEST/$pkg/__init__.py" ] || [ -e "$DEST/$pkg.py" ]; then
        echo "  ok       $pkg"
    elif [ -d "$DEST/$pkg" ] && [ -n "$(find "$DEST/$pkg" -name '*.py' -print -quit)" ]; then
        # A PEP 420 namespace package has no __init__.py and is still perfectly
        # importable. mpl_toolkits is one, which is why matplotlib ships it that way, so
        # requiring __init__.py would fail a tree that is actually complete. Requiring at
        # least one .py keeps the check meaningful: an empty directory still fails.
        echo "  ok       $pkg (namespace package, no __init__.py by design)"
    else
        missing+=("$pkg is missing from $DEST (no __init__.py, no module file, no .py at all)")
    fi
done

# A package directory is not the same as an importable package. These three are the
# files whose absence made numpy, pivy and ifcopenshell fail in ways that named
# something else entirely, so check them by name.
for f in numpy/__config__.py pivy/coin.py ifcopenshell/ifcopenshell_wrapper.py; do
    if [ -s "$DEST/$f" ]; then
        echo "  ok       $f (generated)"
    else
        missing+=("$f -- generated by its build, and the package cannot import without it")
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
