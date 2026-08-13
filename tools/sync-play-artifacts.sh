#!/usr/bin/env bash
# Copy a fresh link's engine triple into play-gui and rebuild the local .data.gz.
#
# The page loads FreeCAD.data.gz, never FreeCAD.data (see freecad-gui.html locateFile),
# so a .gz left over from the previous link pairs new JS with old data and CPython dies
# with "Failed to import encodings module" -- which looks like a broken build, not a
# stale file. Regenerating it is the whole point of this script; do not skip it.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BIN="$ROOT/build-freecad-gui-weh/bin"
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
