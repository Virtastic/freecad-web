#!/bin/bash
# Cross-compile matplotlib 3.9.2 C extensions to wasm32-emscripten and harvest
# them into deps/wasm/lib/mpl-mod/ for the FreeCAD monolith link.
#
# Prerequisites: numpy already built (deps/src/numpy + build-numpy generated
# headers), .qtvenv with meson/ninja/pybind11, emsdk active.
#
# Key gotchas handled:
#  - meson.build uses setuptools_scm for the version -> hardcoded to '3.9.2'.
#  - numpy's generated headers (_numpyconfig.h, __multiarray_api.h, __ufunc_api.h)
#    live in build-numpy, not the source include dir -> copied in.
#  - pybind11's dependency() drags in the HOST python include (wrong LONG_BIT for
#    wasm) -> replaced with an include-only declare_dependency(compile_args:-I...).
#  - freetype 2.6.1 + qhull build as meson subprojects (auto-downloaded).
set -e
cd "$(dirname "$0")"
ROOT="$PWD"
DW="$ROOT/deps/wasm"
MPL="$ROOT/deps/src/matplotlib"
source .qtvenv/bin/activate
source emsdk/emsdk_env.sh >/dev/null 2>&1
export SETUPTOOLS_SCM_PRETEND_VERSION=3.9.2

# 0. source patches (idempotent) so a fresh matplotlib extract builds for wasm.
MB="$MPL/meson.build"
# hardcode version (no git/setuptools_scm for a tarball)
perl -0pi -e "s/version: run_command\(find_program\('python3'\), '-m', 'setuptools_scm', check: true\)\.stdout\(\)\.strip\(\),/version: '3.9.2',/" "$MB"
# pybind11: include-only dep (avoid dragging in the HOST python include -> LONG_BIT)
PB="$(python -c 'import pybind11; print(pybind11.get_include())')"
perl -0pi -e "s{pybind11_dep = dependency\('pybind11', version: '>=2\.6'\)}{pybind11_dep = declare_dependency(compile_args: ['-I$PB'])}" "$MB"
# freetype autofit: AF_WritingSystem_ApplyHintsFunc returns void but the impls
# return FT_Error -> different wasm signature -> call_indirect traps. Match them.
AFT="$MPL/subprojects/freetype-2.6.1/src/autofit/aftypes.h"
if [ -f "$AFT" ]; then
  perl -0pi -e 's/typedef void\n  \(\*AF_WritingSystem_ApplyHintsFunc\)/typedef FT_Error\n  (*AF_WritingSystem_ApplyHintsFunc)/' "$AFT"
fi
# matplotlib imports Pillow (PIL) at module top in a few files; Pillow is not
# ported, so guard the imports (the Agg render / Qt display paths do not need it).
python3 - "$MPL/lib/matplotlib" <<'PYEOF'
import sys, os
base = sys.argv[1]
reps = {
 'colors.py': [("from PIL import Image\n","try:\n    from PIL import Image\nexcept ImportError:\n    Image = None\n"),
               ("from PIL.PngImagePlugin import PngInfo\n","try:\n    from PIL.PngImagePlugin import PngInfo\nexcept ImportError:\n    PngInfo = None\n")],
 'animation.py': [("from PIL import Image\n","try:\n    from PIL import Image\nexcept ImportError:\n    Image = None\n")],
 'image.py': [("import PIL.Image\nimport PIL.PngImagePlugin\n","try:\n    import PIL.Image\n    import PIL.PngImagePlugin\nexcept ImportError:\n    PIL = None\n")],
}
for fn, rs in reps.items():
    p = os.path.join(base, fn); s = open(p).read()
    for old, new in rs:
        if old in s and 'except ImportError' not in s[max(0,s.index(old)-30):s.index(old)]:
            s = s.replace(old, new, 1)
    open(p,'w').write(s)
print("PIL imports guarded")
PYEOF

# 1. stage numpy generated headers into the source include (matplotlib needs them)
NPINC="$ROOT/deps/src/numpy/numpy/_core/include/numpy"
for h in _numpyconfig.h __multiarray_api.h __ufunc_api.h; do
  cp "$(find build-numpy -name "$h" | head -1)" "$NPINC/$h"
done

# 1b. Same host/target header collision numpy hits: meson's python dependency puts
# <cpython>/builddir/build (the HOST build tree, 64-bit pyconfig.h) on the include path
# ahead of builddir/emscripten-mt, so every target unit dies on
#   pyport.h:399: "LONG_BIT definition appears wrong for platform"
# Point sysconfig at the cross build, and move the host pyconfig.h aside for the duration
# -- nothing here compiles host code, the host interpreter is only run. Restored on exit.
MT="$ROOT/deps/src/cpython/builddir/emscripten-mt"
SYSCFG="$(find "$MT" -maxdepth 4 -name '_sysconfigdata_*.py' 2>/dev/null | head -1)"
if [ -n "$SYSCFG" ]; then
  export _PYTHON_SYSCONFIGDATA_NAME="$(basename "$SYSCFG" .py)"
  export PYTHONPATH="$(dirname "$SYSCFG")${PYTHONPATH:+:$PYTHONPATH}"
  echo "cross sysconfig: $_PYTHON_SYSCONFIGDATA_NAME"
fi
HOST_PYCONFIG="$ROOT/deps/src/cpython/builddir/build/pyconfig.h"
if [ -f "$HOST_PYCONFIG" ]; then
  mv "$HOST_PYCONFIG" "$HOST_PYCONFIG.hostonly"
  # shellcheck disable=SC2064
  trap "mv -f '$HOST_PYCONFIG.hostonly' '$HOST_PYCONFIG' 2>/dev/null || true" EXIT
  echo "host pyconfig.h moved aside so the wasm one is found first"
fi

# 2. configure (crossfile provides numpy-include-dir + devnull)
bash tools/gen-crossfiles.sh
rm -rf build-matplotlib
meson setup build-matplotlib deps/src/matplotlib --cross-file matplotlib-crossfile.meson \
  -Dbuildtype=release -Db_lto=false

# 3. build all C extensions + freetype + qhull subprojects
ninja -C build-matplotlib

# 4. harvest: per-extension objects -> libmpl_<name>.a (provide PyInit_*),
#    plus the shared freetype/qhull/agg/ttconv static libs (resolve refs once).
EMAR="$ROOT/emsdk/upstream/emscripten/emar"
mkdir -p "$DW/lib/mpl-mod"
rm -f "$DW"/lib/mpl-mod/*.a
# Match on .so.p, not on a triple: meson names these directories after the HOST triple,
# which is cpython-313-darwin on the build machine and cpython-313-x86_64-linux-gnu in CI.
# Hardcoding darwin meant this loop silently harvested NOTHING anywhere else, leaving an
# empty mpl-mod and a link that drops every matplotlib builtin.
found=0
while IFS= read -r d; do
  [ -d "$d" ] || continue
  name="$(basename "$d")"; name="${name%%.*}"
  find "$d" -name '*.o' -print0 | xargs -0 "$EMAR" rcs "$DW/lib/mpl-mod/libmpl_$name.a"
  found=$((found + 1))
done < <(find build-matplotlib/src -maxdepth 1 -type d -name '*.so.p')
[ "$found" -gt 0 ] || { echo "!! no *.so.p directories under build-matplotlib/src"; exit 1; }
cp build-matplotlib/subprojects/freetype-2.6.1/libfreetype.a "$DW/lib/mpl-mod/"
cp build-matplotlib/subprojects/qhull-8.0.2/libqhull_r.a "$DW/lib/mpl-mod/"
cp build-matplotlib/extern/agg24-svn/libagg.a "$DW/lib/mpl-mod/"
cp build-matplotlib/extern/ttconv/libttconv.a "$DW/lib/mpl-mod/"
echo "matplotlib C-extensions harvested to $DW/lib/mpl-mod:"
ls "$DW/lib/mpl-mod/"
