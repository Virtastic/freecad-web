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
# git apply against a plain directory, with any enclosing repository neutralised.
# See the long comment at the git-apply fallback in apply_one for why this exists and why
# the ceiling matters. Paths are resolved absolutely because GIT_CEILING_DIRECTORIES is
# only honoured for absolute, symlink-free entries.
_fcweb_git_apply() {
  local tree="$1" patch="$2"; shift 2
  local abs parent
  abs="$(cd "$tree" && pwd -P)" || return 1
  parent="$(dirname "$abs")"
  GIT_CEILING_DIRECTORIES="$parent" git -C "$abs" apply "$@" "$patch" 2>/dev/null
}

apply_one() {
  local tree="deps/src/$1" patch="$PATCHES/$2" marker="${3:-}"
  # Optional third argument: "<path-in-tree>::<string>". If that string is present, the
  # patch is treated as applied and left alone.
  #
  # Needed because a patch is not always reversible after the fact. pyside-setup.patch adds
  # the EMSCRIPTEN branch in cmake/Macros/PySideModules.cmake, and then
  # tools/patch-pyside-clang-options.py inserts blocks INSIDE that branch, using a line the
  # patch added as its anchor. Once a build has run, the region matches neither the patched
  # nor the unpatched text, so both `patch --dry-run` and `patch -R --dry-run` fail and a
  # restored source cache aborts the whole job with "tree may be at the wrong version".
  # A marker says SOME version of this patch was applied -- not THIS one. That gap cost
  # the entire 1.1.3 boot: patches/pyside-setup.patch gained the fix that stops shiboken
  # hijacking CPython's PyMethod_New, the cached source tree still carried the old text,
  # the marker matched, the patch was skipped, and the build went green around a source
  # tree that did not contain the fix. So record the patch's hash beside the tree and
  # treat "marker present, hash absent or different" as stale rather than as applied.
  local stamp="$tree/.fcweb-patch-$(basename "$2").sha256"
  local want=""
  if [ -f "$patch" ]; then
    want="$(sha256sum "$patch" 2>/dev/null | cut -d' ' -f1)"
    [ -n "$want" ] || want="$(shasum -a 256 "$patch" | cut -d' ' -f1)"
  fi
  # The marker decides first: it says whether SOME version of the patch is in the tree.
  # Only then does the hash matter -- a freshly fetched, unpatched tree has no stamp and is
  # not stale, it just needs patching. "Marker matches but hash does not" is the dangerous
  # state, and the one that shipped a green build around a tree missing the shiboken fix.
  if [ -n "$marker" ]; then
    local mfile="$tree/${marker%%::*}" mtext="${marker#*::}"
    if [ -f "$mfile" ] && grep -qF -- "$mtext" "$mfile"; then
      # ... and the content has to agree with the stamp. A stamp is a claim ABOUT a
      # tree; only the tree is the tree. This exact branch once passed a pyside-setup
      # whose bufferprocs_py37.cpp lacked the lines the current patch adds.
      if [ -z "$want" ] || { [ -f "$stamp" ] && [ "$(cat "$stamp")" = "$want" ]            && python3 tools/verify-patch-applied.py "$tree" "$patch" --quiet; }; then
        echo "  == $1: already applied (marker + hash + content)"
        [ -n "$want" ] && echo "$want" > "$stamp"
        return 0
      fi
      if [ "${FCWEB_ALLOW_STALE_PATCH:-0}" = "1" ]; then
        echo "  !! $1: tree carries a different $2 (FCWEB_ALLOW_STALE_PATCH=1, continuing)"
        return 0
      fi
      echo "  !! $1: $tree was patched with a DIFFERENT version of $2." >&2
      echo "     Delete the tree so it is re-fetched and re-patched, or set" >&2
      echo "     FCWEB_ALLOW_STALE_PATCH=1 if you know the delta does not matter." >&2
      return 1
    fi
  fi
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
      echo "  == $1: already applied (skip)"; [ -n "$want" ] && echo "$want" > "$stamp"
    elif git -C "$tree" apply --check "$patch" 2>/dev/null; then
      git -C "$tree" apply "$patch"; echo "  ++ $1: applied ${2}"; [ -n "$want" ] && echo "$want" > "$stamp"
    else
      echo "  !! $1: $2 does NOT apply cleanly — tree may be at the wrong commit"; return 1
    fi
    return 0
  fi

  # Tarball extract. patch(1) rather than `git apply`, deliberately: inside this repository's
  # own work tree git would resolve the enclosing .git and bring index semantics to a
  # directory that has nothing to do with it. -R --dry-run first, so re-running is a no-op.
  if patch -d "$tree" -p1 -F0 -R --dry-run --force --silent < "$patch" >/dev/null 2>&1; then
    echo "  == $1: already applied (skip, tarball)"; [ -n "$want" ] && echo "$want" > "$stamp"
  elif patch -d "$tree" -p1 -F0 --dry-run --force --silent < "$patch" >/dev/null 2>&1; then
    patch -d "$tree" -p1 -F0 --silent < "$patch"; echo "  ++ $1: applied ${2} (tarball)"; [ -n "$want" ] && echo "$want" > "$stamp"
  # patch(1) at -F0 is stricter than the diff it is reading. freecad.patch carries a hunk
  # (src/Gui/Application.cpp, the wasm crash-recovery guard) whose six context lines match
  # the pristine 1.1.3 tarball BYTE FOR BYTE at the target line, which was verified one
  # line at a time -- and patch still rejects it, while `git apply` places it at the right
  # offset and `patch -F2` needs two lines of fuzz to agree. So a from-scratch build could
  # not apply the FreeCAD patch at all; it only ever worked because the runner reuses an
  # already-patched deps/src/freecad between runs (measured 2026-09-02).
  #
  # The fallback is `git apply`, NOT fuzz. Fuzz is how a hunk lands in a plausible but
  # wrong scope while the exit status says success -- this project has been bitten by
  # exactly that. git apply matches context exactly and only tolerates a line OFFSET,
  # which is the thing that is genuinely fine here.
  #
  # GIT_CEILING_DIRECTORIES is what makes it safe to use on a tree nested inside this
  # repository: it stops git's upward search at the tree's parent, so no enclosing .git is
  # found and no index semantics apply -- the concern the comment above records. Verified
  # both ways on the builder: without the ceiling git resolves the outer repo, with it the
  # only complaint left is a file the tarball genuinely does not carry.
  elif _fcweb_git_apply "$tree" "$patch" --check; then
    _fcweb_git_apply "$tree" "$patch"
    echo "  ++ $1: applied ${2} (tarball, git apply -- patch(1) refused a hunk it should not have)"
    [ -n "$want" ] && echo "$want" > "$stamp"
  elif _fcweb_git_apply "$tree" "$patch" --reverse --check; then
    echo "  == $1: already applied (skip, tarball, git apply)"; [ -n "$want" ] && echo "$want" > "$stamp"
  else
    # "does not apply cleanly" with nothing else is a message that costs an hour. Re-run
    # WITHOUT --silent and show what actually rejected, plus enough about the two inputs to
    # tell a wrong tree from a mangled patch file.
    echo "  !! $1: $2 does NOT apply cleanly — tree may be at the wrong version"
    echo "     patch:  $(wc -l < "$patch") lines, $(grep -c '^--- ' "$patch") files, md5 $(md5sum < "$patch" | cut -c1-12)"
    echo "     patch file: $(file -b "$patch")"
    echo "     tree:   $tree"
    echo "     patch(1): $(patch --version 2>/dev/null | head -1)"
    echo "     --- first failures ---"
    patch -d "$tree" -p1 -F0 --dry-run --force < "$patch" 2>&1       | grep -vE "^checking file" | head -25 | sed 's/^/     /'
    return 1
  fi
}

# The FreeCAD port is version-specific: patches/freecad.version records the release it was
# rebased onto. Applying it to a different tree is how you get hunks landing in plausible but
# wrong places, so check before touching anything.
check_freecad_version() {
  local tree="deps/src/freecad" want cmake got
  [ -d "$tree" ] || return 0
  want="$(grep -v '^#' "$PATCHES/freecad.version" | tr -d '[:space:]')"
  [ -n "$want" ] || return 0
  cmake="$tree/CMakeLists.txt"
  [ -f "$cmake" ] || { echo "  !! freecad: no CMakeLists.txt in $tree"; return 1; }
  got="$(grep -oE '^set[(]PACKAGE_VERSION_(MAJOR|MINOR|PATCH) "[0-9]+"' "$cmake" | grep -oE '[0-9]+' | paste -sd. -)"
  if [ "$got" != "$want" ]; then
    echo "  !! freecad: tree is $got, but freecad.patch is rebased onto $want."
    echo "     Check out FreeCAD $want, or rebase the patch (tools/freecad-upgrade-scope.sh)."
    return 1
  fi
  echo "  .. freecad: tree is $got, matching freecad.version"
}
check_freecad_version

echo "Applying source patches:"
apply_one freecad       freecad.patch
# Marker rather than a reverse-apply check: tools/patch-pyside-clang-options.py edits inside
# the branch this patch adds, so after one build the file matches neither direction.
apply_one pyside-setup  pyside-setup.patch \
  'sources/pyside6/cmake/Macros/PySideModules.cmake::--clang-option=--target=wasm64-unknown-emscripten'
apply_one occt          occt.patch
apply_one cpython       cpython-ctypes-wasm.patch
# Independent hunks on the same file (the switch, not the EM_JS); either order applies.
apply_one cpython       cpython-trampoline-wasm64.patch
apply_one numpy         numpy.patch
apply_one coin3d        coin3d.patch
# Never applied until now, and it shows: opening the shipped FEMExample.FCStd traps with
# "RuntimeError: unreachable" inside vtkXMLParser::GetXMLByteIndex, which is precisely the
# failure this patch's own comment describes. It was written, committed, and named in the
# deps cache key -- and no line ever applied it. The tree name carries the version because
# that is how the tarball extracts.
apply_one VTK-9.3.1     vtk-expat-wasm-xmlsize.patch   'ThirdParty/expat/CMakeLists.txt::AND NOT EMSCRIPTEN'

# VTK vendors an fmt old enough that it defines its own `enum char8_t` whenever the
# compiler has no native one -- and VTK builds at -std=c++11, so it always does here.
# basic_string_view then instantiates std::char_traits<that enum>, which only ever worked
# because libc++ shipped a generic char_traits primary template. emsdk 6.0.9 does not, so
# ThirdParty/diy2 fails to compile and takes ParallelDIY with it. Toolchain age, not
# pointer width: the same VTK fails identically at wasm32 against the same libc++.
apply_one VTK-9.3.1     vtk-fmt-char8-traits.patch     'ThirdParty/diy2/vtkdiy2/include/vtkdiy2/fmt/format.h::char_traits<char>::length'

# Applying cleanly says the lines went in, not that they went in somewhere they can run.
# Four fixes in this port were written where control never reached them; the last one had
# been spliced into the middle of an if-body, so the rest of that branch sat after a return
# and was dead. patch(1) is perfectly happy with that, and so is the compiler.
if [ -d deps/src/freecad/src ]; then
  echo "Checking port-authored Python is reachable:"
  python3 tools/check-unreachable-fcweb.py deps/src/freecad/src | sed 's/^/  /'
  # ... and the C++ half of the same idea. The port's own switches are the ones that can
  # go quiet: the 1.1.3 boot fix sat behind #ifdef FCWEB_REAL_CPYTHON, defined nowhere,
  # for months of green builds.
  python3 tools/check-fcweb-macros-defined.py deps/src/freecad/src | sed 's/^/  /'
fi

# The preloaded Python tree (--preload-file deps/wasm/pyside-pkg@/pyside-pkg). None of it
# comes out of a build -- it is hand-written glue that aliases the inittab modules to their
# dotted names -- so create the destinations rather than requiring some earlier step to have
# done it. rebuild-pyside-weh.sh makes PySide6/ and shiboken6/; nothing made pivy/, and the
# copy failed the whole job with
#   cp: cannot create regular file '.../pyside-pkg/pivy/__init__.py': No such file or directory
echo "Copying PySide package glue (deps/wasm must already exist):"
if [ -d deps/wasm ]; then
  mkdir -p deps/wasm/pyside-pkg/PySide6 deps/wasm/pyside-pkg/shiboken6 \
           deps/wasm/pyside-pkg/pivy deps/wasm/include/shiboken
  cp -v patches/pyside-pkg-glue/PySide6/__init__.py           deps/wasm/pyside-pkg/PySide6/__init__.py
  cp -v patches/pyside-pkg-glue/shiboken6/__init__.py         deps/wasm/pyside-pkg/shiboken6/__init__.py
  cp -v patches/pyside-pkg-glue/pivy/__init__.py              deps/wasm/pyside-pkg/pivy/__init__.py
  cp -v patches/pyside-pkg-glue/include-shiboken/sbkversion.h deps/wasm/include/shiboken/sbkversion.h
else
  echo "  (deps/wasm not present yet — build the dependency stack first; see README.md)"
fi
echo "done."
