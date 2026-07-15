#!/usr/bin/env bash
# Regenerate every stored patch from the current state of the vendored deps/ git trees.
# Run this after making ANY source change under deps/src/* so the fix is captured for
# reproducible rebuilds (deps/ itself is gitignored). Idempotent; only rewrites the .patch
# files. See README.md for the apply direction (apply.sh) and the regenerable/glue pieces.
set -euo pipefail
cd "$(dirname "$0")/.."          # repo root
PATCHES="patches"

# repo (under deps/src) : output patch file
MAP=(
  "freecad:freecad.patch"
  "pyside-setup:pyside-setup.patch"
  "occt:occt.patch"
  "cpython:cpython-ctypes-wasm.patch"
  "numpy:numpy.patch"
)

for pair in "${MAP[@]}"; do
  repo="${pair%%:*}"; out="$PATCHES/${pair##*:}"
  tree="deps/src/$repo"
  if [ ! -d "$tree/.git" ]; then echo "skip $repo (not a git checkout)"; continue; fi
  git -C "$tree" diff > "$out"
  lines=$(wc -l < "$out" | tr -d ' ')
  files=$(git -C "$tree" diff --name-only | wc -l | tr -d ' ')
  printf "  %-14s -> %-28s %s files, %s lines\n" "$repo" "$out" "$files" "$lines"
done
echo "done. Review 'git status $PATCHES' and commit the updated patch files."
