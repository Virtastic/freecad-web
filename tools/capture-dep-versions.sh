#!/usr/bin/env bash
# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) Virtastic
# Capture exactly which source revision each dependency was built from.
#
# WHY THIS EXISTS
#
# `deps/` is gitignored, and the build scripts reference dependencies by an UNVERSIONED path
# -- `deps/src/occt`, `deps/src/coin3d`, `deps/src/cpython`, `deps/src/freecad`. Only two of
# the twenty-three carry a version anywhere: VTK-9.3.1 and hdf5-1.14.3. For everything else
# the version is whatever happens to be sitting on the build machine's disk.
#
# So the production binary cannot be reproduced by anyone else, and not by this machine either
# once those directories change. That is not a hypothetical: it is exactly how CalculiX ended
# up with 69 routines silently stubbed in a clean build while production's solver worked --
# the build machine had f2c workarounds nobody had captured, and nobody noticed until someone
# built from clean on 2026-08-16.
#
# CalculiX was one instance. This is the general case, across the whole stack.
#
# HOW TO USE IT
#
#     bash tools/capture-dep-versions.sh > deps-versions.txt
#
# Run it ON THE BUILD MACHINE, in the repo root, with deps/ populated as it was for the
# release. Commit the output. After that a clean rebuild has a target to hit, and any drift
# becomes a diff rather than a mystery.
#
# It only reads. It clones nothing, fetches nothing, and changes nothing.
set -uo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"

echo "# freecad-web dependency manifest"
echo "# generated: $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
echo "# host     : $(uname -srm)"
echo "#"
echo "# One line per dependency: <name> <kind> <revision-or-version> [detail]"
echo "# 'unknown' means the tree carries no version marker at all -- those are the ones that"
echo "# make the build unreproducible, and the ones worth pinning first."
echo

if [ ! -d deps/src ]; then
  echo "ERROR: no deps/src here. Run this on the build machine, from the repo root." >&2
  exit 1
fi

for d in deps/src/*/; do
  name="$(basename "$d")"

  # A git checkout is the best case: the commit is exact.
  if [ -d "$d/.git" ]; then
    rev="$(git -C "$d" rev-parse HEAD 2>/dev/null || echo unknown)"
    desc="$(git -C "$d" describe --tags --always --dirty 2>/dev/null || echo '')"
    origin="$(git -C "$d" remote get-url origin 2>/dev/null || echo '')"
    printf '%-16s git      %s  %s  %s\n' "$name" "$rev" "${desc:--}" "${origin:--}"
    continue
  fi

  # Otherwise look for a version the project states about itself. Ordered most to least
  # trustworthy; the first hit wins.
  ver=''
  for probe in VERSION version.txt VERSION.txt .version; do
    [ -s "$d/$probe" ] && { ver="$(head -1 "$d/$probe" | tr -d '\r')"; break; }
  done
  [ -z "$ver" ] && [ -s "$d/CMakeLists.txt" ] && \
    ver="$(grep -m1 -oiE 'project *\([^)]*VERSION +[0-9][0-9.]*' "$d/CMakeLists.txt" \
           | grep -oE '[0-9][0-9.]*' | head -1)"
  [ -z "$ver" ] && [ -s "$d/setup.py" ] && \
    ver="$(grep -m1 -oE "version *= *['\"][^'\"]+" "$d/setup.py" | sed "s/.*['\"]//")"
  [ -z "$ver" ] && [ -s "$d/pyproject.toml" ] && \
    ver="$(grep -m1 -oE '^version *= *"[^"]+' "$d/pyproject.toml" | sed 's/.*"//')"
  # The directory name itself often carries it (VTK-9.3.1, hdf5-1.14.3).
  [ -z "$ver" ] && ver="$(echo "$name" | grep -oE '[0-9]+([._][0-9]+)+' | head -1)"

  # Content hash as a last resort: not a version, but it distinguishes two trees and proves
  # whether a later checkout is the same bits.
  files="$(find "$d" -type f \( -name '*.c' -o -name '*.h' -o -name '*.cpp' -o -name '*.hxx' \
           -o -name '*.f' -o -name '*.py' \) 2>/dev/null | wc -l | tr -d ' ')"
  hash="$(find "$d" -type f \( -name '*.c' -o -name '*.h' -o -name '*.cpp' -o -name '*.hxx' \
          -o -name '*.f' -o -name '*.py' \) -exec cksum {} + 2>/dev/null \
          | awk '{s+=$1; n++} END {printf "%s-%s", (n?s:0), (n?n:0)}')"
  printf '%-16s tarball  %-24s  files=%s  cksum=%s\n' \
         "$name" "${ver:-unknown}" "$files" "$hash"
done

echo
echo "# --- toolchains ---"
for t in emsdk emsdk2; do
  if [ -d "$t/.git" ]; then
    printf '%-16s git      %s  %s\n' "$t" \
      "$(git -C "$t" rev-parse HEAD 2>/dev/null || echo unknown)" \
      "$(cat "$t/upstream/emscripten/emscripten-version.txt" 2>/dev/null | tr -d '"' || echo '')"
  elif [ -d "$t" ]; then
    printf '%-16s dir      %s\n' "$t" \
      "$(cat "$t/upstream/emscripten/emscripten-version.txt" 2>/dev/null | tr -d '"' || echo unknown)"
  fi
done
qt="$(ls -d qt/*/ 2>/dev/null | head -1)"
[ -n "$qt" ] && printf '%-16s dir      %s\n' "qt" "$qt"

echo
echo "# --- what the release actually shipped ---"
for f in play-gui/FreeCAD.wasm play-gui/FreeCAD.js play-gui/FreeCAD.data \
         play-gui/ccx.wasm play-gui/gmsh.wasm; do
  [ -s "$f" ] && printf '%-24s %10s bytes  md5=%s\n' "$(basename "$f")" \
    "$(wc -c < "$f" | tr -d ' ')" "$(md5sum "$f" 2>/dev/null | cut -d' ' -f1 || \
       md5 -q "$f" 2>/dev/null)"
done
