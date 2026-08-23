#!/usr/bin/env bash
# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) Virtastic
# Build the freecad test image from the fetched artifacts (run after fetch-artifacts.sh).
# Applies the GL patch table then packages infra/Dockerfile (nginx + the site). Mirrors the
# "Apply the GL patch table" + "Build image" steps in .github/workflows/deploy-ovh.yml.
set -euo pipefail
cd "$(dirname "$0")/../.."   # repo root
TAG="${TAG:-freecad:test}"
REL="$(cat .release-tag 2>/dev/null || echo dirty)"

[ -s play-gui/FreeCAD.wasm ] || { echo "FATAL: play-gui/FreeCAD.wasm missing (run fetch-artifacts.sh first)"; exit 1; }

# GL patch table (~33 hand-derived patches to emscripten's GL glue). The release asset is normally
# already patched, so this is usually a no-op that reports "already applied" — but running it means
# a change to the patch table reaches the test site without a relink. Idempotent; --check verifies
# invariants and fails the build if a patch is missing. python3 is required (present in the Jenkins
# container; installed there once).
python3 tools/patch-freecad-js.py play-gui/FreeCAD.js
python3 tools/patch-freecad-js.py play-gui/FreeCAD.js --check

echo "==> building $TAG from release $REL"
DOCKER_BUILDKIT=1 docker build --network=host \
  --build-arg "FCWEB_BUILD=${REL}+test" \
  -t "$TAG" -f infra/Dockerfile .
echo "==> built $TAG"
docker image inspect "$TAG" --format '    size: {{.Size}} bytes  created: {{.Created}}'
