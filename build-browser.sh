#!/bin/bash
# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) Virtastic
# Build a BROWSER variant of FreeCADCmd: no NODERAWFS; preload the python stdlib
# and FreeCAD resources into MEMFS so it runs in a browser tab (served via COOP/COEP).
set -e
cd "$(dirname "$0")"
. toolchain/env.sh
ROOT="$PWD"
CPY="$ROOT/deps/src/cpython"
INST="$ROOT/freecad-install"

# Preload mappings: host_dir@/mount_point
# PROXY_TO_PTHREAD: run main() on a worker so the browser main thread stays free
# for pthread proxying (FreeCAD/OCCT block on worker threads — blocking the main
# thread directly deadlocks in the browser, unlike node).
export FC_LINK_MODE_FLAGS="\
-sPROXY_TO_PTHREAD=1 \
-sPTHREAD_POOL_SIZE_STRICT=0 \
--preload-file $CPY/Lib@/pylib \
--preload-file $ROOT/build-freecad/Ext@/fc-ext \
--preload-file $INST/Mod@/freecad/Mod \
--preload-file $INST/Ext@/freecad/Ext"

echo "=== reconfigure for browser (relink only) ==="
bash configure-freecad.sh > /tmp/fc-configure.log 2>&1
echo "configure exit=$?"
ninja -C build-freecad bin/FreeCADCmd.js
mkdir -p play
cp build-freecad/bin/FreeCADCmd.js   play/
cp build-freecad/bin/FreeCADCmd.wasm play/
cp build-freecad/bin/FreeCADCmd.data play/ 2>/dev/null || true
cp build-freecad/bin/FreeCADCmd.worker.js play/ 2>/dev/null || true
echo "=== browser artifacts in play/ ==="
ls -la play/FreeCADCmd.* 2>/dev/null | awk '{print $5, $9}'
