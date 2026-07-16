#!/usr/bin/env bash
# Rename matplotlib's freetype-2.6.1 internal functions that CLASH with Qt's bundled
# freetype (a newer version with different signatures). Both archives are on the FreeCAD.js
# link line; wasm-ld would warn "signature mismatch: FT_Request_Metrics / ft_module_get_service"
# and route the mismatched callers through a trapping stub (benign for text, but a latent
# trap if matplotlib's own font path runs). Renaming matplotlib's copies keeps the two
# freetypes fully separate (Qt keeps the originals). Recompile the 10 .o that define/reference
# them with -D rename macros and replace them in the archive. Run AFTER the matplotlib freetype
# build, BEFORE the final FreeCAD.js link. Idempotent.
set -euo pipefail
cd "$(dirname "$0")/.."
. toolchain/env.sh 2>/dev/null || source emsdk/emsdk_env.sh >/dev/null 2>&1
FT=deps/src/matplotlib/subprojects/freetype-2.6.1
AR=deps/wasm/lib/mpl-mod/libfreetype.a
REN="-DFT_Request_Metrics=FT_Request_Metrics_mpl -Dft_module_get_service=ft_module_get_service_mpl"
# member-name : source (the definer ftbase + the 9 referencers)
FILES="src_base_ftbase.c.o:src/base/ftbase.c src_base_ftgxval.c.o:src/base/ftgxval.c \
src_base_ftotval.c.o:src/base/ftotval.c src_cff_cff.c.o:src/cff/cff.c \
src_cid_type1cid.c.o:src/cid/type1cid.c src_psaux_psaux.c.o:src/psaux/psaux.c \
src_sfnt_sfnt.c.o:src/sfnt/sfnt.c src_truetype_truetype.c.o:src/truetype/truetype.c \
src_type1_type1.c.o:src/type1/type1.c src_type42_type42.c.o:src/type42/type42.c"
tmp=$(mktemp -d)
for pair in $FILES; do
  obj="${pair%%:*}"; src="${pair##*:}"
  emcc -c -O2 -pthread -DFT2_BUILD_LIBRARY $REN -I"$FT/include" "$FT/$src" -o "$tmp/$obj"
done
emar r "$AR" "$tmp"/*.o
rm -rf "$tmp"
# verify the clash is gone
if emsdk/upstream/bin/llvm-nm "$AR" 2>/dev/null | grep -qwE "T (FT_Request_Metrics|ft_module_get_service)$"; then
  echo "!! rename FAILED — original symbols still global in $AR" >&2; exit 1
fi
echo "freetype symbol clash fixed: FT_Request_Metrics/ft_module_get_service renamed to *_mpl in $AR"
