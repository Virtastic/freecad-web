#!/bin/bash
# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) Virtastic
# Rebuild FreeCAD (keep-going) and summarize distinct errors + files.
cd "$(dirname "$0")"
. toolchain/env.sh >/dev/null 2>&1
ninja -C build-freecad -k 0 > /tmp/fc-build.log 2>&1
echo "ninja exit=$?"
echo "progress: $(grep -aoE '\[[0-9]+/[0-9]+\]' /tmp/fc-build.log | tail -1)"
echo "=== libs linked ==="; ls build-freecad/lib/*.so 2>/dev/null | xargs -n1 basename 2>/dev/null
echo "=== distinct error messages ==="
grep -aoE "error: .*" /tmp/fc-build.log | sed -E 's/[0-9]+/N/g' | sort | uniq -c | sort -rn | head -12
echo "=== distinct error files ==="
grep -aoE "freecad/src/[a-zA-Z0-9_/.-]+\.(cpp|cxx|c|h|hpp):[0-9]+:[0-9]+: (error|fatal)" /tmp/fc-build.log \
  | sed -E 's/:[0-9]+:[0-9]+:.*//' | sort -u | head -20
