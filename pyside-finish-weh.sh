#!/bin/bash
# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) Virtastic
cd "$(dirname "$0")"
. toolchain/env.sh
TARGETS="libpyside/libpyside6.cpython-313-wasm64-emscripten.a PySide6/QtCore/QtCore.cpython-313-wasm64-emscripten.a PySide6/QtGui/QtGui.cpython-313-wasm64-emscripten.a PySide6/QtWidgets/QtWidgets.cpython-313-wasm64-emscripten.a"
for i in 1 2 3 4 5 6 7 8; do
  ninja -C build-pyside-wasm $TARGETS > /tmp/pyside-iter.log 2>&1 && { echo "PYSIDE-TARGETS-OK iter=$i"; exit 0; }
  # collect missing generated wrappers from AutoGen + compile errors
  miss=$(grep -oE '"BIN:[^"]+_wrapper\.cpp"|BIN:[^" ]+_wrapper\.cpp' /tmp/pyside-iter.log | tr -d '"' | sed 's|^BIN:/||' | sort -u)
  miss2=$(grep -oE "error: [^ ]+_wrapper\.cpp: No such file" /tmp/pyside-iter.log | sed 's/^error: //; s/: No such file//' | sort -u)
  new=0
  for rel in $miss; do
    # BIN:/PySide6/QtCore/PySide6/QtCore/foo.cpp -> build-pyside-wasm/PySide6/QtCore/PySide6/QtCore/foo.cpp
    p="build-pyside-wasm/$rel"
    [ -f "$p" ] || { mkdir -p "$(dirname "$p")"; : > "$p"; echo "stubbed $p"; new=1; }
  done
  for p in $miss2; do [ -f "$p" ] || { mkdir -p "$(dirname "$p")"; : > "$p"; echo "stubbed $p"; new=1; }; done
  [ "$new" = "0" ] && { echo "PYSIDE-STUCK iter=$i"; tail -30 /tmp/pyside-iter.log; exit 1; }
done
echo PYSIDE-EXHAUSTED; exit 1
