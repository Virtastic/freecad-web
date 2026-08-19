#!/usr/bin/env bash
# Measure what upgrading FreeCAD costs, by trying the patch instead of estimating it.
#
# patches/freecad.patch is 31,718 lines across 83 files and is the single largest piece of
# this port. The port now targets 1.1.3 (see patches/freecad.version); moving to a newer
# release means rebasing it again, and the only honest way
# to size that is to fetch the new tree and see which hunks land.
#
# WHAT IT REPORTS
#
#   applies clean   hunks that need no work at all
#   fuzzy           applied with offset/fuzz -- review, but essentially free
#   FAILED          hunks that need hand work; these are the actual job
#
# It writes .rej files so each failure is a concrete diff rather than a count.
#
# KNOWN PATH MOVES. FreeCAD 1.1 reorganised src/Gui into subdirectories, so six patched
# files exist at new paths. The patch is remapped onto them before anything is attempted --
# without that they read as "deleted" and the report overstates the work by six files.
#
#     src/Gui/DlgParameterImp.cpp      -> src/Gui/Dialogs/DlgParameterImp.cpp
#     src/Gui/DlgPreferencesImp.cpp    -> src/Gui/Dialogs/DlgPreferencesImp.cpp
#     src/Gui/DlgRunExternal.cpp       -> src/Gui/Dialogs/DlgRunExternal.cpp
#     src/Gui/NavigationStyle.cpp      -> src/Gui/Navigation/NavigationStyle.cpp
#     src/Gui/SelectionView.cpp        -> src/Gui/Selection/SelectionView.cpp
#     src/Gui/SoFCUnifiedSelection.cpp -> src/Gui/Selection/SoFCUnifiedSelection.cpp
#
# USAGE
#     bash tools/freecad-upgrade-scope.sh [tag]        # default 1.1.3
set -uo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TAG="${1:-1.1.3}"
work="${TMPDIR:-/tmp}/fcupgrade-$TAG"
mkdir -p "$work"

src="$work/FreeCAD-$TAG"
if [ ! -d "$src" ]; then
  echo "fetching FreeCAD $TAG ..."
  curl -fsSL -o "$work/src.tar.gz" \
    "https://github.com/FreeCAD/FreeCAD/archive/refs/tags/$TAG.tar.gz" || {
      echo "could not fetch tag $TAG" >&2; exit 1; }
  mkdir -p "$src"
  tar xzf "$work/src.tar.gz" -C "$src" --strip-components=1
fi
echo "tree: $src"

# Remap the moved paths so the attempt measures CONTENT drift, not the reorganisation.
pat="$work/freecad-remapped.patch"
sed -e 's|\(a\|b\)/src/Gui/DlgParameterImp\.cpp|\1/src/Gui/Dialogs/DlgParameterImp.cpp|g' \
    -e 's|\(a\|b\)/src/Gui/DlgPreferencesImp\.cpp|\1/src/Gui/Dialogs/DlgPreferencesImp.cpp|g' \
    -e 's|\(a\|b\)/src/Gui/DlgRunExternal\.cpp|\1/src/Gui/Dialogs/DlgRunExternal.cpp|g' \
    -e 's|\(a\|b\)/src/Gui/NavigationStyle\.cpp|\1/src/Gui/Navigation/NavigationStyle.cpp|g' \
    -e 's|\(a\|b\)/src/Gui/SelectionView\.cpp|\1/src/Gui/Selection/SelectionView.cpp|g' \
    -e 's|\(a\|b\)/src/Gui/SoFCUnifiedSelection\.cpp|\1/src/Gui/Selection/SoFCUnifiedSelection.cpp|g' \
    "$root/patches/freecad.patch" > "$pat"
echo "remapped 6 moved paths"

echo
echo "attempting the patch (dry run, per file) ..."
ok=0; fuzzy=0; failed=0
declare -a badfiles=()
# --batch so it never prompts; -N so an already-applied hunk is skipped, not queried.
out="$(cd "$src" && patch -p1 --dry-run --batch --forward -F3 < "$pat" 2>&1)"
while IFS= read -r line; do
  case "$line" in
    *"succeeded at"*)   fuzzy=$((fuzzy+1)) ;;
    *"FAILED at"*)      failed=$((failed+1)) ;;
    "checking file "*|"patching file "*) ok=$((ok+1)) ;;
    *"Hunk #"*ignored*) failed=$((failed+1)) ;;
  esac
done <<< "$out"

echo "$out" | grep -E "^(checking|patching) file|FAILED|succeeded at|can.t find file" > "$work/report.txt"
# Which files had at least one failure?
cur=""
while IFS= read -r l; do
  case "$l" in
    "checking file "*) cur="${l#checking file }" ;;
    "patching file "*) cur="${l#patching file }" ;;
    *FAILED*) badfiles+=("$cur") ;;
  esac
done <<< "$out"

echo
echo "  files patched      : $ok"
echo "  hunks with fuzz    : $fuzzy   (applied, worth a look)"
echo "  hunks FAILED       : $failed  <- the actual work"
echo
if [ "${#badfiles[@]}" -gt 0 ]; then
  echo "  files needing hand work:"
  printf '%s\n' "${badfiles[@]}" | sort -u | sed 's/^/     /'
fi
echo
echo "full report: $work/report.txt"
echo
echo "NOTE: this measures the PATCH only. An upgrade also needs the dependency stack"
echo "rebuilt against the new tree and a relink, and neither is possible until"
echo "gl_compat.h and qprocess_stub.h are captured (tools/capture-build-machine-headers.sh)."
