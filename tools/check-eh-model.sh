#!/usr/bin/env bash
# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) Virtastic
# Which objects on the link line were built with JS exception handling?
#
#     bash tools/check-eh-model.sh [extra dirs...]
#
# This whole port is -fwasm-exceptions. An object compiled -fexceptions instead references
# emscripten's JS-EH runtime, which a wasm-EH link does not provide, and wasm-ld says only:
#
#     undefined symbol: __cxa_find_matching_catch_2   (referenced by root reference
#                                                      (e.g. compiled C/C++ code))
#     undefined symbol: __resumeException
#     undefined symbol: llvm_eh_typeid_for
#
# "root reference (e.g. compiled C/C++ code)" names nothing, so the only way to find the
# culprit is to look. Guessing has already cost two rounds: -fexceptions was found and fixed
# in configure-ctypes.sh and configure-pillow.sh, and the SAME three symbols came back.
#
# Mixing the two models in one link is the OCCT defect from ROADMAP 12, in its fourth
# incarnation on this branch (OCCT, PySide's -fno-exceptions, _ctypes/PIL, and whatever this
# prints).
set -u
cd "$(dirname "$0")/.."

NM="emsdk/upstream/bin/llvm-nm"
[ -x "$NM" ] || NM="$(command -v llvm-nm || command -v nm || true)"
[ -n "$NM" ] || { echo "no llvm-nm -- cannot inspect anything" >&2; exit 1; }

JSEH='__cxa_find_matching_catch|__resumeException|llvm_eh_typeid_for'

DIRS=(deps/wasm/lib deps/wasm/shiboken6 build-pyside-wasm build-shiboken-wasm weh-objs
      build-freecad-gui-weh build-ifcopenshell build-pivy-wasm "$@")

echo "scanning for JS-EH references (-fexceptions) in a wasm-EH build"
echo "nm: $NM"
found=0
scanned=0
for d in "${DIRS[@]}"; do
    [ -d "$d" ] || continue
    while IFS= read -r f; do
        scanned=$((scanned + 1))
        # --undefined-only: a definition of these is fine (the runtime itself); a
        # REFERENCE is what drags JS-EH into the link.
        hits="$("$NM" --undefined-only "$f" 2>/dev/null | grep -cE "$JSEH" || true)"
        if [ "${hits:-0}" != 0 ]; then
            echo "  JS-EH  $f  ($hits reference(s))"
            found=$((found + 1))
        fi
    done < <(find "$d" \( -name '*.a' -o -name '*.o' \) -type f 2>/dev/null)
done

echo "scanned $scanned object(s)/archive(s); $found reference JS-EH"
if [ "$found" != 0 ]; then
    echo
    echo "Each file above was compiled -fexceptions. Rebuild it with"
    echo "    -fwasm-exceptions -sSUPPORT_LONGJMP=wasm"
    echo "to match Qt, OCCT, Coin, CPython and FreeCAD."
fi
# Diagnostic: never fail the build on this, the link already does that with less information.
exit 0
