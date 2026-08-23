#!/bin/bash
# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) Virtastic
# Generate the meson cross-files from their .in templates, substituting the repo root.
#
# The cross-files need ABSOLUTE paths (meson resolves [binaries] against PATH, not the
# source dir), which is why they cannot simply be committed with relative paths. They
# used to be committed with one developer's home directory baked in, so nobody else
# could build. Generating them makes the build work from wherever the tree lives.
#
# Idempotent. Run from anywhere; the root is derived from this script's location.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd)"

for tmpl in "$ROOT"/*.meson.in; do
    [ -e "$tmpl" ] || continue
    out="${tmpl%.in}"
    sed "s|@ROOT@|$ROOT|g" "$tmpl" > "$out"
    echo "[gen-crossfiles] $(basename "$out")"
done

# Fail loudly rather than let a stale placeholder reach meson, which would report a
# missing compiler instead of a missing substitution.
if grep -l '@ROOT@' "$ROOT"/*.meson 2>/dev/null; then
    echo "[gen-crossfiles] ERROR: unsubstituted @ROOT@ remains in the output above" >&2
    exit 1
fi
