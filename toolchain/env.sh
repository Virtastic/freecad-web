#!/bin/bash
# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) Virtastic
# Single source of truth for the FreeCAD-Web wasm toolchain.
# Usage:  . toolchain/env.sh   (source it; do NOT execute)
#
# Pins emscripten to 6.0.9 and builds for wasm64 (MEMORY64). Every build/spike script
# must source this first so nothing accidentally falls back to Homebrew emscripten.
#
# WHY 6.0.9 AND NOT A QT-SANCTIONED VERSION. Qt for WebAssembly pins one emscripten per Qt
# minor: Qt 6.9 -> 3.1.70 (which is why this project sat there), Qt 6.11 -> 4.0.7. But
# wasm64 with pthreads and a MAXIMUM_MEMORY above 4 GB is only fixed in 5.0.1/6.x
# (emscripten#26311, PR #26357), and the pthread mailbox gap is emscripten#21159. Both
# pins cannot be honoured at once, so Qt 6.11 is deliberately run on an emscripten it has
# never validated. Expect to carry Qt patches; this is the same class of problem the old
# emsdk2/wasm-opt shim existed to solve.
FCWEB_EMSDK_VERSION=6.0.9

# Repo root = parent of this script's directory (toolchain/). Self-locating so
# the tree can live anywhere; requires sourcing (not executing) this file.
export ROOT="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd)"

# Bring emcc/em++/emcmake/node/python onto PATH from the pinned SDK.
source "$ROOT/emsdk/emsdk_env.sh" >/dev/null 2>&1

# Cross-compiled dependency prefix: .a -> $DW/lib, headers -> $DW/include.
export DW="$ROOT/deps/wasm"

# ---- wasm64 --------------------------------------------------------------------------
# -m64 is the CURRENT spelling. -sMEMORY64=1 still works but is deprecated; do not write it
# into new scripts.
#
# This goes in EMCC_CFLAGS rather than into each build script because emcc appends
# EMCC_CFLAGS to EVERY invocation -- compiles, links, and the throwaway probe compiles that
# autotools and meson run during configure. That last part is the reason: a configure test
# built for wasm32 would measure wasm32 sizeof/alignment and bake the answers into a build
# that is then linked for wasm64. Setting it here retargets all ~40 build scripts at once
# and keeps configure honest, which naming the flag per-script would not.
# Appended idempotently: this file is sourced by ~50 build scripts and by workflow steps
# that then call one of them, so a plain append would repeat the flag once per nesting
# level. Harmless in effect, but it makes EMCC_CFLAGS unreadable in a log, which is the
# one place anyone looks when the target is in doubt.
case " $EMCC_CFLAGS " in
  *" -m64 "*) ;;
  *) export EMCC_CFLAGS="${EMCC_CFLAGS:+$EMCC_CFLAGS }-m64" ;;
esac

# -sWASM_LEGACY_EXCEPTIONS=0: use the STANDARDIZED wasm exception opcodes, not the phase-3
# legacy ones. Two reasons, and the second is why it is here rather than in a build script.
#
# Correctness: this project compiles -fwasm-exceptions and targets Chrome 137+, which
# implements the final proposal. 3.1.70 defaulted to the legacy opcodes; 6.x does not, and
# tools/check-eh-model.sh already asserts no legacy EH symbols survive.
#
# And it unbreaks the ports. With SUPPORT_LONGJMP=wasm and legacy exceptions still in play,
# emscripten selects the "legacysjlj" variant of a port and builds it with
#     -sWASM_LEGACY_EXCEPTIONS=True
# -- a stringified Python bool, which 6.0.9 rejects outright:
#     emcc: error: attempt to set `WASM_LEGACY_EXCEPTIONS` to `True`; use 1/0
# That killed the OCCT build 15 seconds in, while compiling the freetype port, on a flag
# nothing in this repo passes. Setting it to 0 here selects the non-legacy variant instead,
# so the port is never built down that path. Note it cannot be fixed by appending the flag
# to a build script: the port system appends its own copy LAST, and emcc takes the last.
# Appended idempotently: this file is sourced by ~50 build scripts and by workflow steps
# that then call one of them, so a plain append would repeat the flag once per nesting
# level. Harmless in effect, but it makes EMCC_CFLAGS unreadable in a log, which is the
# one place anyone looks when the target is in doubt.
case " $EMCC_CFLAGS " in
  *" -sWASM_LEGACY_EXCEPTIONS=0 "*) ;;
  *) export EMCC_CFLAGS="${EMCC_CFLAGS:+$EMCC_CFLAGS }-sWASM_LEGACY_EXCEPTIONS=0" ;;
esac

# Sanity echo so a wrong toolchain is obvious immediately.
echo "[env] emcc: $(emcc --version 2>/dev/null | head -1)"
echo "[env] which emcc: $(command -v emcc)"
echo "[env] DW=$DW"

# Do not trust the flag, measure the target. __wasm64__ is defined by the compiler itself,
# so this fails loudly if EMCC_CFLAGS was clobbered or the SDK does not understand -m64 --
# rather than silently producing a wasm32 archive that only explodes at final link.
if emcc $EMCC_CFLAGS -dM -E -x c /dev/null 2>/dev/null | grep -q __wasm64__; then
  echo "[env] target: wasm64 (__wasm64__ defined)"
else
  echo "[env] FATAL: emcc is NOT targeting wasm64. EMCC_CFLAGS=$EMCC_CFLAGS" >&2
  echo "[env] Every archive built now would be wasm32 and fail at the final link." >&2
  return 1 2>/dev/null || exit 1
fi
