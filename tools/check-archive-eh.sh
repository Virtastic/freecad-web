#!/usr/bin/env bash
# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) Virtastic
# Which wasm exception-handling model is each archive built for?
#
#     bash tools/check-archive-eh.sh [--prune] <dir-or-archive>...
#
# emscripten has two incompatible EH instruction sets and one module may use only one:
#
#     legacy   try / catch / delegate / rethrow      -sWASM_LEGACY_EXCEPTIONS=1 (the 6.0.9 DEFAULT)
#     new      try_table / throw_ref                 -sWASM_LEGACY_EXCEPTIONS=0 (what env.sh sets)
#
# The setting is [compile+link]: an object carries the model it was compiled with, and
# wasm-ld links either without complaint. Node validates the mix. Chrome does not:
#
#     CompileError: Compiling function #33757:"_wrap_delete_SbDict(_object*, _object*)"
#     failed: module uses a mix of legacy and new exception handling instructions
#
# That was link 33963711535, the first wasm64 link to reach the boot gate: every static gate
# green, and the application never started. toolchain/env.sh had switched the whole build to
# the new model (commit c604b5a, to unbreak the ports), but the dependency caches have
# literal keys and per-package "already built, skipping" guards, so libCoin.a and
# libxerces-c.a built before that commit were linked in unchanged -- 5,000 legacy functions
# in a module of 75,000 new ones.
#
# Nothing cheaper than the opcodes tells the two apart: both models record the same
# "+exception-handling" in target_features (measured on 6.0.9 -- probe objects built with
# =0 and =1 have identical feature sections), so this disassembles. It is the same shape as
# tools/check-archive-target.py, which prunes wasm32 archives from a wasm64 cache so the
# lane's own guards rebuild them: --prune deletes every archive that carries a legacy
# instruction, and prints what it deleted.
#
# An archive with no EH instructions at all (C code, -fno-exceptions) is neutral and passes.
# Archives are scanned in parallel; the first legacy instruction ends an archive's scan.
set -u
cd "$(dirname "$0")/.."

OBJDUMP="emsdk/upstream/bin/llvm-objdump"
[ -x "$OBJDUMP" ] || OBJDUMP="$(command -v llvm-objdump || true)"
[ -n "$OBJDUMP" ] || { echo "::error::no llvm-objdump -- cannot inspect anything"; exit 1; }
export OBJDUMP

prune=0
if [ "${1:-}" = "--prune" ]; then prune=1; shift; fi
[ $# -gt 0 ] || { echo "usage: $0 [--prune] <dir-or-archive>..." >&2; exit 2; }

# One line per file: "<legacy|new|neutral> <path>". An objdump line is
#     <hex offset>: <hex bytes...> <mnemonic> ...
classify() {
    local f="$1"
    if "$OBJDUMP" -d "$f" 2>/dev/null | grep -qE -m1 '^[[:space:]]*[0-9a-f]+:([[:space:]]+[0-9a-f]{2})+[[:space:]]+(try|delegate|rethrow)([[:space:]]|$)'; then
        echo "legacy $f"
    elif "$OBJDUMP" -d "$f" 2>/dev/null | grep -qE -m1 '^[[:space:]]*[0-9a-f]+:([[:space:]]+[0-9a-f]{2})+[[:space:]]+(try_table|throw_ref)([[:space:]]|$)'; then
        echo "new $f"
    else
        echo "neutral $f"
    fi
}
export -f classify

jobs="$(nproc 2>/dev/null || echo 4)"
results="$(for p in "$@"; do
               if [ -d "$p" ]; then find "$p" \( -name '*.a' -o -name '*.o' \) -type f; elif [ -f "$p" ]; then echo "$p"; fi
           done | sort | xargs -r -P "$jobs" -I{} bash -c 'classify "$1"' _ {})"

legacy=0; new=0; neutral=0
while IFS=' ' read -r kind f; do
    [ -n "$kind" ] || continue
    case "$kind" in
        legacy)
            legacy=$((legacy + 1))
            if [ "$prune" = 1 ]; then rm -f "$f"; echo "  PRUNED legacy-EH  $f"; else echo "  LEGACY  $f"; fi ;;
        new) new=$((new + 1)) ;;
        *) neutral=$((neutral + 1)) ;;
    esac
done <<< "$results"

echo "scanned $((legacy + new + neutral)) archive(s)/object(s): $new new-EH, $neutral without EH, $legacy legacy-EH"
if [ "$legacy" != 0 ]; then
    if [ "$prune" = 1 ]; then
        echo "  pruned $legacy; the lane's build steps rebuild them under toolchain/env.sh (WASM_LEGACY_EXCEPTIONS=0)"
        exit 0
    fi
    echo "::error::$legacy archive(s) carry legacy EH instructions; linked with the rest they make a module Chrome refuses to compile"
    exit 1
fi
