#!/usr/bin/env bash
# Translate every CalculiX source locally and report exactly which routines get stubbed.
#
# The same question build-ccx.yml answers, in about two minutes on a laptop instead of a
# ten-minute CI dispatch. It runs the real pipeline -- tools/f77ify.py, then f2c with the
# flags build-ccx-weh.sh uses -- so the stub list it prints is the one the build would get.
#
# It does NOT build the wasm module and it does NOT run the validation decks. A green list
# here means "these routines translate", not "the solver is correct". The decks in
# .github/workflows/build-ccx.yml remain the only thing that checks the numbers.
#
# SETUP
#     bash tools/build-f2c-local.sh          # once; needs an emsdk for its bundled clang
#
# USAGE
#     bash tools/ccx-translate-check.sh <path-to-ccx_2.22/src>
#
# Exits non-zero if anything outside the expected set fails to translate, so it can gate a
# change before spending a runner on it.
set -uo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="${1:-}"
[ -n "$SRC" ] && [ -d "$SRC" ] || { echo "usage: bash $0 <ccx_2.22/src>" >&2; exit 2; }
F2C="$root/f2c-local/f2c"
[ -x "$F2C" ] || F2C="$root/f2c-local/f2c.exe"
[ -x "$F2C" ] || { echo "no local f2c -- run: bash tools/build-f2c-local.sh" >&2; exit 2; }

work="$(mktemp -d 2>/dev/null || echo "${TMPDIR:-/tmp}/ccxcheck.$$")"
mkdir -p "$work/f77" "$work/c" "$work/src"
echo "translating $(ls -1 "$SRC"/*.f | wc -l | tr -d ' ') files -> $work"

# Apply patches/ccx-*.patch to a COPY first, exactly as build-ccx.yml does. Skipping this
# made the first version of this script report patch.f and gencontelem_n2f.f as stubbed --
# they are not; they depend on ccx-patch-lda.patch and ccx-wasm-automatic-array.patch. A
# checker that does not reproduce the build's inputs reports the build's answer wrongly.
cp "$SRC"/*.f "$work/src/" 2>/dev/null
napplied=0
for pf in "$root"/patches/ccx-*.patch; do
  [ -e "$pf" ] || continue
  if patch -d "$work" -p1 --silent --force < "$pf" >/dev/null 2>&1      || patch -d "$work/src" -p0 --silent --force < "$pf" >/dev/null 2>&1; then
    napplied=$((napplied+1))
  else
    echo "::error::$(basename "$pf") does not apply -- the stub list below would be wrong"
    exit 2
  fi
done
echo "  applied $napplied CalculiX patch(es)"
SRC="$work/src"

# python3 is not universal -- Windows/msys ships `python`. Resolve it, and do NOT hide the
# rewriter's stderr: a silent failure here produced an empty work directory and a cheerful
# "translated: 2", which looks like success and is nothing of the kind.
PY=python3
command -v python3 >/dev/null 2>&1 || PY=python
command -v "$PY" >/dev/null 2>&1 || { echo "no python on PATH" >&2; exit 2; }

# f2c resolves INCLUDE relative to cwd, so every rewritten file has to share one directory.
n_in=0; n_out=0
for f in "$SRC"/*.f; do
  n_in=$((n_in+1))
  if "$PY" "$root/tools/f77ify.py" "$f" "$work/f77/$(basename "$f")" 2>>"$work/f77ify.err"; then
    n_out=$((n_out+1))
  else
    echo "::error::f77ify failed on $(basename "$f") -- see $work/f77ify.err"
  fi
done
if [ "$n_out" -ne "$n_in" ]; then
  echo "::error::f77ify produced $n_out of $n_in files; refusing to report a stub list from that"
  exit 2
fi
[ -e "$root/bridge/ccx_reductions.f" ] && cp "$root/bridge/ccx_reductions.f" "$work/f77/"
[ -e "$root/bridge/ccx_matmul.f" ] && cp "$root/bridge/ccx_matmul.f" "$work/f77/"

cd "$work/f77"
ok=0; inc=0; fail=()
for f in *.f; do
  # A file with no subprogram head is an INCLUDE of data (gauss.f, xlocal.f), not a
  # translation unit; f2c cannot translate one alone and its "failure" means nothing.
  n=$(grep -viE '^[cC*!]' "$f" \
      | grep -ciE '^ {6,}([a-z0-9_*() ]*[[:space:]])?(subroutine|function|program|block[[:space:]]*data)[[:space:]]+[a-z_]' \
      || true)
  if [ "${n:-0}" -eq 0 ]; then inc=$((inc+1)); continue; fi
  if "$F2C" -a -A -NC1000 -d"$work/c" "$f" >/dev/null 2>"$work/$f.log" \
     && ! grep -q '^Error' "$work/$f.log"; then
    ok=$((ok+1))
  else
    fail+=("$f")
  fi
done

echo
echo "  translated : $ok"
echo "  includes   : $inc  (not routines)"
echo "  stubbed    : ${#fail[@]}"
for f in "${fail[@]}"; do
  printf '     %-22s %s\n' "$f" "$(grep -m1 '^Error' "$work/$f.log" 2>/dev/null | sed 's/.*: //')"
done

# The set that is expected to fail, and why, per docs-ccx-stubbed-routines.md.
EXPECTED=" e_c3d_us45.f slavintmortar.f slavintpoints.f "
rc=0
for f in "${fail[@]}"; do
  case "$EXPECTED" in *" $f "*) ;; *) echo "::error::$f is newly stubbed"; rc=1 ;; esac
done
[ "$rc" = 0 ] && echo && echo "  no routine outside the documented set is stubbed."
exit $rc
