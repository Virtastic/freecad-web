#!/bin/bash
set -e
cd "$(dirname "$0")"
. toolchain/env.sh
echo "=== VTK ==="; rm -rf build-vtk; bash configure-vtk-weh.sh
echo "=== IFCOPENSHELL ==="; rm -rf build-ifcopenshell; bash configure-ifcopenshell-weh.sh
echo "LANE5-ALL-DONE"
