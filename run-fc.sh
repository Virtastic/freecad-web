#!/bin/bash
# Run headless FreeCADCmd (wasm) in node with resources + python stdlib wired.
cd "$(dirname "$0")"
ROOT="$PWD"
INST="$ROOT/freecad-install"
CPY="$ROOT/deps/src/cpython"
export HOME="$ROOT/fc-home"; mkdir -p "$HOME/.FreeCAD" "$HOME/.local/share" "$HOME/.config" "$HOME/.cache"
FREECAD_WASM_HOME="$INST" HOME="$HOME" \
  FCWEB_PYLIB="$CPY/Lib:$CPY/builddir/emscripten-mt:$ROOT/build-freecad/Ext" \
  node "$INST/bin/freecad-run.js" "$@"
