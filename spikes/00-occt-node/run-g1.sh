#!/bin/bash
# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) Virtastic
# G1: compile occt_probe.cpp against our own libTK*.a and run under node.
set -e
cd "$(dirname "$0")"
. ../../toolchain/env.sh
INC="$DW/include/opencascade"
em++ occt_probe.cpp -O2 -fexceptions -pthread \
  -I"$INC" \
  $DW/lib/libTK*.a --use-port=freetype \
  -sALLOW_MEMORY_GROWTH=1 -sEXIT_RUNTIME=0 -sNODERAWFS=1 -sPROXY_TO_PTHREAD=0 \
  -o occt_probe.js
echo "=== running G1 probe in node ==="
node occt_probe.js
