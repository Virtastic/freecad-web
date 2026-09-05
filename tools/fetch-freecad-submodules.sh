#!/bin/bash
# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) Virtastic
# Fetch the git submodules the FreeCAD source tarball does not carry.
#
#     bash tools/fetch-freecad-submodules.sh          # tree at deps/src/freecad
#
# GitHub's tag tarballs contain no submodules, and FreeCAD 1.1 keeps four: GSL,
# OndselSolver, AddonManager and googletest. Everything that compiles FreeCAD needs GSL
# (src/Gui/CMakeLists.txt SEND_ERRORs without it), the production configure has
# BUILD_ASSEMBLY on so OndselSolver has to come too, and AddonManager is a submodule
# since 1.1 -- which is why patches/freecad.patch, generated on a machine with the full
# tree, carries hunks for src/Mod/AddonManager/NetworkManager.py. Run this BEFORE
# tools/check-patch-applies.py, or those hunks report "missing from tree" against a tree
# that is merely incomplete. googletest stays out; it serves ENABLE_DEVELOPER_TESTS only.
#
# AddonManager is pinned to the commit FreeCAD 1.1.3 itself points at (read from the tag,
# not from a branch: an addon manager newer than the app it ships in is a bug waiting).
# Update adm_sha when patches/freecad.version moves.
set -e
cd "$(dirname "$0")/.."
tree="${1:-deps/src/freecad}"
[ -e "$tree/CMakeLists.txt" ] || { echo "!! no FreeCAD tree at $tree" >&2; exit 1; }

gsl="$tree/src/3rdParty/GSL"
if [ ! -e "$gsl/include/gsl/gsl" ]; then
  mkdir -p "$gsl"
  curl -fsSL -o /tmp/gsl.tar.gz https://github.com/microsoft/GSL/archive/refs/tags/v4.0.0.tar.gz
  tar xzf /tmp/gsl.tar.gz -C "$gsl" --strip-components=1
fi
[ -e "$gsl/include/gsl/gsl" ] || { echo "::error::GSL missing -- src/Gui needs it"; exit 1; }
echo "  GSL:          $(ls "$gsl/include/gsl" | wc -l) headers"

ond="$tree/src/3rdParty/OndselSolver"
if [ ! -e "$ond/CMakeLists.txt" ]; then
  mkdir -p "$ond"
  curl -fsSL -o /tmp/ondsel.tar.gz https://github.com/Ondsel-Development/OndselSolver/archive/refs/heads/main.tar.gz
  tar xzf /tmp/ondsel.tar.gz -C "$ond" --strip-components=1
fi
[ -e "$ond/CMakeLists.txt" ] || { echo "::error::OndselSolver missing -- BUILD_ASSEMBLY needs it"; exit 1; }
echo "  OndselSolver: present"

adm="$tree/src/Mod/AddonManager"
adm_sha=937b6877239dc78ef59eeefe8099e5f14243eda1
if [ ! -e "$adm/AddonManager.py" ]; then
  mkdir -p "$adm"
  curl -fsSL -o /tmp/addonmgr.tar.gz "https://codeload.github.com/FreeCAD/AddonManager/tar.gz/$adm_sha"
  tar xzf /tmp/addonmgr.tar.gz -C "$adm" --strip-components=1
fi
[ -e "$adm/AddonManager.py" ] || { echo "::error::AddonManager missing -- BUILD_ADDONMGR and freecad.patch need it"; exit 1; }
echo "  AddonManager: present ($(ls "$adm"/*.py 2>/dev/null | wc -l) modules)"
