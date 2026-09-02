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

RUN="${1:?run id, or a directory holding FreeCAD.js/.wasm/.data}"
TAG="${2:?release tag}"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

# The first argument may be a DIRECTORY instead of a run id.
#
# This exists because `gh run download` is not always possible. On 2026-08-26 the account
# hit its GitHub artifact storage quota and every upload that day was refused, so the only
# copy of a finished link lived in the runner's own workspace -- which the next link
# overwrites. Yesterday that was solved by copying the files off the box by hand and then
# having no way to feed them to this script. Now there is one:
#
#     scp -i ~/Documents/SSH/ovh_nostalgia #         'ubuntu@ORIGIN-IP-REDACTED:/home/ubuntu/actions-runner-virtastic/_work/freecad-web/freecad-web/build-freecad-gui-weh/bin/FreeCAD.*' ./rescued/
#     bash tools/publish-release.sh ./rescued build-20260826-something
#
# A release must never be cut from a directory nobody has gated. That is true of the
# artifact path too, and is why the header above says to boot it first.
if [ -d "$RUN" ]; then
    echo "== using the local directory $RUN (not a CI artifact)"
    BIN="$RUN"
else
    echo "== download the link artifact from run $RUN"
    gh run download "$RUN" -n freecad-wasm -D "$WORK"
    BIN="$WORK/build-freecad-gui-weh/bin"
fi
for f in FreeCAD.js FreeCAD.wasm FreeCAD.data; do
    [ -s "$BIN/$f" ] || { echo "!! missing $f in $BIN" >&2; exit 1; }
done
ls -la "$BIN"

# The payload check, here as well as in the link and the deploy canary. This is the last
# point before an artifact becomes "latest", and "latest" is one push away from production.
echo "== does the payload carry its Python packages?"
# python3 on the build box and in CI; plain python on a Windows workstation, where the
# python3 shim opens the Microsoft Store instead of running anything. Without this the
# check "failed" here for want of an interpreter and refused a perfectly good artifact --
# a gate that fails for the wrong reason is still a broken gate.
# Chosen by RUNNING it, not by finding it: on Windows "python3" resolves to a Microsoft
# Store app-execution alias that exists, is on PATH, and does nothing but print an advert.
PY_BIN=""
for c in python3 python py; do
    if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys' >/dev/null 2>&1; then
        PY_BIN="$c"; break
    fi
done
[ -n "$PY_BIN" ] || { echo "!! no working python on PATH for the payload check" >&2; exit 1; }
"$PY_BIN" tools/check-payload-packages.py "$BIN/FreeCAD.js" || {
    echo "!! refusing to publish: this artifact would boot and then fail FEM, the Addon" >&2
    echo "!! Manager and Draft. That build was live for two days on 2026-08-25." >&2
    exit 1
}

echo "== carry over gmsh/ccx from the current latest release"
# gh infers the repo from the git remote. Run from a rescued directory outside a checkout
# -- which is exactly what the --dir path above is for -- and it dies with
# "fatal: not a git repository". Name the repo explicitly so both paths work.
export GH_REPO="${GH_REPO:-Virtastic/freecad-web}"
PREV="$(gh release view --json tagName -q .tagName)"
echo "   previous latest: $PREV"
for f in gmsh.js gmsh.wasm ccx.js ccx.wasm; do
    # Reuse a copy already sitting in the staging directory. `gh release download`
    # has no overwrite, so a present file made this step FAIL outright -- and on a
    # flaky link (measured 2026-08-31: repeated i/o timeouts to
    # release-assets.githubusercontent.com) re-fetching 30 MB of unchanged modules
    # is the step most likely to lose a publish. These four are byte-identical
    # across releases by definition: they are carried over, never rebuilt here.
    if [ -s "$BIN/$f" ]; then
        echo "   reusing staged $f ($(stat -c%s "$BIN/$f") bytes)"
        continue
    fi
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
