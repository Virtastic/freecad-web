#!/usr/bin/env bash
# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) Virtastic
# Copy a fresh link's engine triple into play-gui and rebuild the local .data.gz.
#
# The page loads FreeCAD.data.gz, never FreeCAD.data (see freecad-gui.html locateFile),
# so a .gz left over from the previous link pairs new JS with old data and CPython dies
# with "Failed to import encodings module" -- which looks like a broken build, not a
# stale file. Regenerating it is the whole point of this script; do not skip it.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BIN="$ROOT/build-freecad-gui-weh/bin"
# wasm64 NOTE: these numbers were measured on the wasm32 build. 64-bit pointers make the
# module bigger -- expect the correct link to land somewhere above 152 MB, and the
# skipped-wasm-opt case to move up with it. The 200 MB threshold is kept unchanged on
# purpose: it is a discriminator between "optimised" and "wasm-opt never ran", not a
# budget, and guessing a new value before a single wasm64 link has been measured would
# either mask the failure it exists to catch or fail a good build. RE-BASELINE IT from the
# first green wasm64 link: set it a little above the real size, not to a round number.
# MEASURED on that link (run 33961285555): FreeCAD.wasm is 196,115,387 bytes after
# wasm-opt, so the ceiling is now 202,000,000 -- 3% above it, and still far below the
# ~300 MB an un-optimised wasm64 link would weigh.
# A correct link lands near 152 MB. 234 MB means wasm-opt did not run (or was killed
# mid-link, which leaves the un-optimized intermediate sitting in bin/ looking finished).
# Shipping that is a silent, large performance regression -- refuse it here.
sz=$(stat -f %z "$BIN/FreeCAD.wasm" 2>/dev/null || stat -c %s "$BIN/FreeCAD.wasm")
if [ "$sz" -gt 202000000 ]; then
  echo "FreeCAD.wasm is ${sz} bytes -- that is the pre-wasm-opt size. Re-run the link." >&2
  exit 1
fi
cp "$BIN/FreeCAD.js" "$BIN/FreeCAD.wasm" "$BIN/FreeCAD.data" "$ROOT/play-gui/"
python3 "$ROOT/tools/patch-freecad-js.py" "$ROOT/play-gui/FreeCAD.js"
rm -f "$ROOT/play-gui/FreeCAD.data.gz"
gzip -6 -k "$ROOT/play-gui/FreeCAD.data"
# Verify by CONTENT, not mtime: `gzip -k` copies the source's timestamp onto the .gz, so
# a "is the gz newer?" test can never prove freshness (it reported this correct pair as
# stale). Decompressing and comparing takes a couple of seconds and is airtight.
gzip -dc "$ROOT/play-gui/FreeCAD.data.gz" | cmp -s - "$ROOT/play-gui/FreeCAD.data" \
  || { echo "FreeCAD.data.gz does not match FreeCAD.data" >&2; exit 1; }
ls -la "$ROOT/play-gui/FreeCAD.js" "$ROOT/play-gui/FreeCAD.wasm" "$ROOT/play-gui/FreeCAD.data.gz"
