#!/usr/bin/env bash
# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) Virtastic
# Post-deploy contract test against a deployed freecad origin (or the container port directly).
# Usage: smoke-test.sh <base-url>     e.g. smoke-test.sh http://192.168.1.131:8084
set -uo pipefail
BASE="${1:?usage: smoke-test.sh <base-url>}"; BASE="${BASE%/}"
FAILED=0
pass() { printf '  \033[32mok\033[0m   %s\n' "$1"; }
fail() { printf '  \033[31mFAIL\033[0m %s\n       -> %s\n' "$1" "$2"; FAILED=$((FAILED+1)); }
get()  { curl -s --max-time 30 "$@"; }
hdrs() { curl -s -D - -o /dev/null --max-time 30 "$@"; }
code() { curl -s -o /dev/null -w '%{http_code}' --max-time 60 "$@"; }
has()  { grep -qi -- "$1" <<<"$2"; }

echo "==> freecad serving contract: $BASE"

# 1. Cross-origin isolation — FreeCAD is pthreads/SharedArrayBuffer, so BOTH are mandatory here.
H="$(hdrs "$BASE/")"
has '^cross-origin-opener-policy: *same-origin'   "$H" && pass "COOP: same-origin"   || fail "COOP header" "SharedArrayBuffer will be unavailable"
has '^cross-origin-embedder-policy: *require-corp' "$H" && pass "COEP: require-corp" || fail "COEP header" "cross-origin isolation off"

# 2. Root serves the FreeCAD GUI (freecad-gui.html), not a 404 / directory listing.
B="$(get "$BASE/")"
has 'freecad' "$B" && pass "root serves the FreeCAD GUI" || fail "GUI at /" "root did not return freecad-gui.html"

# 2b. LGPL attribution reachable same-origin: the license page, the license text itself, and the
# link from the app shell to it. A deploy that drops these is a compliance regression, not cosmetics.
[ "$(code "$BASE/legal.html")" = 200 ] && pass "legal.html served" || fail "legal.html" "LGPL attribution page missing"
[ "$(code "$BASE/LICENSE")"    = 200 ] && pass "LICENSE served"    || fail "LICENSE" "license text not served same-origin"
has 'legal.html' "$B" && pass "GUI links to the license page" || fail "license link" "freecad-gui.html has no legal.html link"

# 3. The engine triple is present and typed. FreeCAD.data is the 341 MB preload FS.
[ "$(code "$BASE/FreeCAD.wasm")" = 200 ] && pass "FreeCAD.wasm served" || fail "FreeCAD.wasm" "engine wasm missing"
[ "$(code "$BASE/FreeCAD.js")"   = 200 ] && pass "FreeCAD.js served"   || fail "FreeCAD.js" "engine loader missing"
[ "$(code "$BASE/FreeCAD.data")" = 200 ] && pass "FreeCAD.data served" || fail "FreeCAD.data" "preload filesystem missing"
has '^content-type: *application/wasm' "$(hdrs "$BASE/FreeCAD.wasm")" && pass "FreeCAD.wasm is application/wasm" || fail "wasm mime" "wrong Content-Type"

# 4. The payload INSIDE the engine, not just the engine.
#
# Everything above passes for a build whose preload holds the Python standard library and
# nothing else -- which is exactly what freecad.virtastic.app AND freecad.dev.virtastic.app
# were both serving on 2026-08-26, for two days, while returning 200 for every asset with
# every header correct. FEM, the Addon Manager and Draft were all dead. The app booted in
# 13 s and drew a box the whole time.
if command -v python3 >/dev/null 2>&1; then
    _js="$(mktemp)"
    if get -o "$_js" "$BASE/FreeCAD.js" && [ -s "$_js" ]; then
        if python3 "$(dirname "$0")/../../tools/check-payload-packages.py" "$_js" >/dev/null 2>&1; then
            pass "payload carries its Python packages"
        else
            fail "payload packages" "numpy/matplotlib/PIL/ifcopenshell missing -- FEM, the Addon Manager and Draft cannot start"
        fi
    else
        fail "payload packages" "could not fetch FreeCAD.js to inspect"
    fi
    rm -f "$_js"
else
    echo "  SKIP  payload package check (no python3 here)"
fi

echo
[ "$FAILED" = 0 ] && { echo "==> contract OK"; exit 0; } || { echo "==> $FAILED contract failure(s)"; exit 1; }
