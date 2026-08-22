#!/usr/bin/env bash
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

# 3. The engine triple is present and typed. FreeCAD.data is the 341 MB preload FS.
[ "$(code "$BASE/FreeCAD.wasm")" = 200 ] && pass "FreeCAD.wasm served" || fail "FreeCAD.wasm" "engine wasm missing"
[ "$(code "$BASE/FreeCAD.js")"   = 200 ] && pass "FreeCAD.js served"   || fail "FreeCAD.js" "engine loader missing"
[ "$(code "$BASE/FreeCAD.data")" = 200 ] && pass "FreeCAD.data served" || fail "FreeCAD.data" "preload filesystem missing"
has '^content-type: *application/wasm' "$(hdrs "$BASE/FreeCAD.wasm")" && pass "FreeCAD.wasm is application/wasm" || fail "wasm mime" "wrong Content-Type"

echo
[ "$FAILED" = 0 ] && { echo "==> contract OK"; exit 0; } || { echo "==> $FAILED contract failure(s)"; exit 1; }
