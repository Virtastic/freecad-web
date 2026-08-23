#!/usr/bin/env bash
# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) Virtastic
# Fetch the prebuilt WASM artifacts from a GitHub Release into play-gui/.
#
# freecad-web does NOT compile in CI: the toolchain build (boost + cpython + gmsh + calculix +
# FreeCAD itself to WASM) is a multi-hour, multi-gigabyte job that runs out-of-band and publishes
# FreeCAD.js/.wasm/.data (+ gmsh, ccx) as assets on a GitHub Release. This mirrors the "Fetch build
# artifacts from the release" step in .github/workflows/deploy-ovh.yml.
#
# Needs GH_TOKEN (read access to the private repo) and REPO=Virtastic/freecad-web. Optionally
# RELEASE_TAG to pin a release; default is the latest.
set -euo pipefail
_cfg="$(dirname "$0")/config.env"
# shellcheck disable=SC1090
[ -f "$_cfg" ] && . "$_cfg"
GH_TOKEN="${GH_TOKEN:?set GH_TOKEN (a GitHub token with read access to the private repo)}"
REPO="${REPO:-Virtastic/freecad-web}"
REQ_TAG="${RELEASE_TAG:-}"

cd "$(dirname "$0")/../.."   # repo root
api="https://api.github.com/repos/$REPO/releases"
if [ -n "$REQ_TAG" ]; then rel="$api/tags/$REQ_TAG"; else rel="$api/latest"; fi

json=$(curl -fsSL -H "Authorization: Bearer $GH_TOKEN" -H "Accept: application/vnd.github+json" "$rel")
tag=$(printf '%s' "$json" | python3 -c 'import sys,json;print(json.load(sys.stdin)["tag_name"])')
echo "==> release: $tag"
mkdir -p play-gui
for name in FreeCAD.js FreeCAD.wasm FreeCAD.data gmsh.js gmsh.wasm ccx.js ccx.wasm; do
  aid=$(printf '%s' "$json" | python3 -c "import sys,json;print(next(a['id'] for a in json.load(sys.stdin)['assets'] if a['name']=='$name'))")
  echo "    downloading $name (asset $aid)"
  curl -fL -H "Authorization: Bearer $GH_TOKEN" -H "Accept: application/octet-stream" \
    "$api/assets/$aid" -o "play-gui/$name"
done
test -s play-gui/FreeCAD.wasm && test -s play-gui/FreeCAD.data \
  && test -s play-gui/gmsh.wasm && test -s play-gui/ccx.wasm \
  || { echo "FATAL: artifacts missing/empty after download" >&2; exit 1; }
echo "$tag" > .release-tag
echo "==> fetched $(du -sh play-gui | cut -f1) for release $tag"
