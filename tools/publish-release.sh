#!/usr/bin/env bash
# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) Virtastic
# Publish a boot-verified link artifact as the latest GitHub Release, ready for the
# Jenkins test deploy and the OVH prod deploy (both consume the LATEST release).
#
#     bash tools/publish-release.sh <run-id> <tag>
#     bash tools/publish-release.sh 32641287144 build-20260823-freecad113
#
# Copies gmsh.js/gmsh.wasm/ccx.js/ccx.wasm from the current latest release: those modules
# are built by their own lanes and unchanged by the FreeCAD link. Both deploy pipelines
# (ci/jenkins/fetch-artifacts.sh and deploy-ovh.yml) require all seven asset names.
#
# DO NOT run this before the artifact has been booted locally: "latest" is one
# Build-Now/branch-push away from the test server and production respectively.
set -euo pipefail
cd "$(dirname "$0")/.."

RUN="${1:?run id}"
TAG="${2:?release tag}"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

echo "== download the link artifact from run $RUN"
gh run download "$RUN" -n freecad-wasm -D "$WORK"
BIN="$WORK/build-freecad-gui-weh/bin"
for f in FreeCAD.js FreeCAD.wasm FreeCAD.data; do
    [ -s "$BIN/$f" ] || { echo "!! missing $f in the artifact" >&2; exit 1; }
done
ls -la "$BIN"

echo "== carry over gmsh/ccx from the current latest release"
PREV="$(gh release view --json tagName -q .tagName)"
echo "   previous latest: $PREV"
for f in gmsh.js gmsh.wasm ccx.js ccx.wasm; do
    gh release download "$PREV" -p "$f" -D "$BIN"
    [ -s "$BIN/$f" ] || { echo "!! could not fetch $f from $PREV" >&2; exit 1; }
done

echo "== create release $TAG (as latest)"
gh release create "$TAG" \
    --title "$TAG" \
    --notes "FreeCAD 1.1.3 wasm build from run $RUN. GL patch table applied; wasm name section kept (--profiling-funcs) so error reports carry function names. gmsh/ccx carried over from $PREV." \
    --latest \
    "$BIN/FreeCAD.js" "$BIN/FreeCAD.wasm" "$BIN/FreeCAD.data" \
    "$BIN/gmsh.js" "$BIN/gmsh.wasm" "$BIN/ccx.js" "$BIN/ccx.wasm"

echo "== done. Next:"
echo "   1. Jenkins: Build Now on FreeCAD-Web-Test (or the curl trigger via the builder)"
echo "   2. smoke:   ci/jenkins/smoke-test.sh http://192.168.1.131:8084"
echo "   3. prod:    git push origin main:ovhcloud   (deploy-ovh.yml picks up this release)"
