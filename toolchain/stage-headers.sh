#!/bin/bash
# Put the hand-written compat headers where every build script force-includes them from
# ($DW/include), and refuse to continue if one is missing.
#
# WHY
#
# Three headers are force-included into Coin3D, all of FreeCAD (C *and* C++), PySide and
# all three link commands:
#
#     deps/wasm/include/gl_compat.h        legacy fixed-function GL declarations for a
#                                          GLES/WebGL2 target
#     deps/wasm/include/coin_intrusive.h   boost::intrusive_ptr adapters for SoBase
#     deps/wasm/include/qprocess_stub.h    inert QProcess (Qt-for-WebAssembly has none)
#
# Ten tracked files consume them. Nothing in the repository produced them: they lived only
# on the build machine, under a gitignored path, so the failure surfaced as an inscrutable
# compile error a long way from the cause -- if it surfaced at all.
#
# Scope, measured rather than assumed: Coin3D builds fine against an EMPTY gl_compat.h (CI
# run 32099719534, libCoin.a 11,785,732 bytes, no errors). The FreeCAD build is where the
# header is expected to matter. Objects built against an empty one are still not
# production-equivalent and must not be linked into a release.
#
# coin_intrusive.h is now reconstructed and tracked (toolchain/include/). gl_compat.h and
# qprocess_stub.h are NOT -- see the message below. This script makes that gap a named,
# immediate failure instead of a mystery 40 minutes into a build.
#
# THE BUILD MACHINE'S COPY ALWAYS WINS. If a header already exists in $DW/include this
# script leaves it alone and reports a diff against the tracked one. The tracked copies are
# reconstructions; the originals are the reference. Set FCWEB_FORCE_STAGE_HEADERS=1 to
# overwrite deliberately.
#
# Usage:  bash toolchain/stage-headers.sh     (after sourcing toolchain/env.sh, or standalone)
set -uo pipefail

ROOT="${ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd)}"
DW="${DW:-$ROOT/deps/wasm}"
SRC="$ROOT/toolchain/include"

mkdir -p "$DW/include"

# --- stage the headers this repo actually carries -------------------------------------
for h in "$SRC"/*.h; do
  [ -e "$h" ] || continue
  name="$(basename "$h")"
  dest="$DW/include/$name"

  if [ -e "$dest" ] && [ "${FCWEB_FORCE_STAGE_HEADERS:-0}" != "1" ]; then
    if cmp -s "$h" "$dest"; then
      echo "[headers] $name: already staged, identical"
    else
      echo "[headers] $name: PRESENT AND DIFFERENT -- keeping the existing copy."
      echo "[headers]   Existing (authoritative): $dest"
      echo "[headers]   Tracked (reconstruction): $h"
      echo "[headers]   If the existing one is the build machine's original, capture it:"
      echo "[headers]     bash tools/capture-build-machine-headers.sh"
      diff -u "$dest" "$h" | sed 's/^/[headers]   | /' | head -40
    fi
  else
    cp "$h" "$dest"
    echo "[headers] $name: staged from toolchain/include"
  fi
done

# --- the ones that are still missing -----------------------------------------------------
missing=0
for name in gl_compat.h coin_intrusive.h qprocess_stub.h; do
  [ -e "$DW/include/$name" ] || { echo "[headers] MISSING: $DW/include/$name"; missing=1; }
done

if [ "$missing" = 1 ]; then
  if [ "${FCWEB_ALLOW_MISSING_GL_COMPAT:-0}" = "1" ]; then
    # Diagnostic mode only. An empty gl_compat.h lets the compiler run and REPORT what the
    # real header has to declare -- the error list is the specification for reconstructing
    # it. The resulting objects are NOT production-equivalent; nothing built this way may be
    # linked into a release.
    for n in gl_compat.h coin_intrusive.h qprocess_stub.h; do
      [ -e "$DW/include/$n" ] || : > "$DW/include/$n"
    done
    echo "::warning::FCWEB_ALLOW_MISSING_GL_COMPAT=1 -- staging an EMPTY gl_compat.h."
    echo "[headers] DIAGNOSTIC BUILD. Not production-equivalent. Do not ship anything linked"
    echo "[headers] from these objects. The compile errors that follow are the header's spec."
  else
    cat >&2 <<'EOF'

[headers] ---------------------------------------------------------------------------
[headers] This build cannot proceed: a force-included header is missing.
[headers]
[headers]   gl_compat.h       legacy fixed-function GL declarations (GLES/WebGL2 target)
[headers]   coin_intrusive.h  boost::intrusive_ptr adapters for SoBase
[headers]   qprocess_stub.h   inert QProcess -- Qt-for-WebAssembly has no subprocesses
[headers]
[headers] Every build script passes these as `-include`. The missing ones have never been
[headers] tracked here -- they exist only on the machine that produced the current release,
[headers] under the gitignored deps/ path.
[headers]
[headers] Coin3D does compile without gl_compat.h (CI run 32099719534 built libCoin.a clean
[headers] against an empty one). The FreeCAD build is the one expected to need it, since it
[headers] force-includes it into every C and C++ unit and calls the legacy GL entry points
[headers] that gl_legacy_stubs.c defines.
[headers]
[headers] ON THAT MACHINE, capture it once and commit the result:
[headers]
[headers]     bash tools/capture-build-machine-headers.sh
[headers]     git add toolchain/include && git commit
[headers]
[headers] To derive what it must contain instead (a diagnostic build that WILL fail, but
[headers] whose errors enumerate every missing declaration):
[headers]
[headers]     FCWEB_ALLOW_MISSING_GL_COMPAT=1 bash toolchain/stage-headers.sh
[headers] ---------------------------------------------------------------------------

EOF
    exit 1
  fi
fi

echo "[headers] ok -- $DW/include"
ls -la "$DW/include"/*.h 2>/dev/null | sed 's/^/[headers]   /'
exit 0
