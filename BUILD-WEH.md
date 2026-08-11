# Reproducing the production build (wasm-EH + JSPI)

This is the lane that produces what runs on <https://freecad.virtastic.app>.
It is a **full-world rebuild**: everything must be compiled with wasm exceptions
(`-fwasm-exceptions`). Mixing in one JS-EH (`-fexceptions`) library silently
reintroduces `invoke_*` JS trampolines, and JSPI cannot suspend across a JS
frame — dialogs stop returning the user's real choice.

## Toolchains

| Path | Version | Used for |
|---|---|---|
| `emsdk/` | 3.1.70 (pinned) | all compiling and linking |
| `emsdk2/` | 4.0.23 | **only** its `wasm-opt` (binaryen v125) |

emsdk 3.1.70 ships binaryen v119, which cannot parse wasm-EH and fails the
link. `wasm-opt` is shimmed to the emsdk2 binary; the
`unexpected binaryen version: 125 (expected 119)` warning at link is expected.

## Order

Dependencies first — each must finish before the next starts.

```bash
bash build-boost-weh.sh            # boost
bash build-xercesc-weh.sh          # xerces-c
bash configure-occt-weh.sh         # OCCT   (gates OCC_CONVERT_SIGNALS off, see below)
bash configure-vtk-weh.sh          # VTK
bash configure-coin-weh.sh         # Coin3D
bash deps-weh-lane2.sh             # yaml-cpp, etc.
bash deps-weh-lane2b.sh
bash configure-kiwisolver-weh.sh
bash configure-matplotlib-weh.sh   # uses matplotlib-crossfile.meson
bash configure-ifcopenshell-weh.sh
bash rebuild-pyside-weh.sh         # shiboken6 + PySide6
bash pyside-finish-weh.sh
bash lane4-weh.sh; bash lane4b-weh.sh; bash lane5-weh.sh
```

Qt 6.9.0 is built from source into `qt/6.9.0/wasm_mt_weh` with
`-feature-wasm-exceptions -feature-wasm-jspi`.

Then FreeCAD itself:

```bash
bash configure-gui-weh.sh                      # cmake configure -> build-freecad-gui-weh
cd build-freecad-gui-weh && ninja              # ~1h cold
bash scratchpad/linkcmds/fc-linkcmd-weh.sh     # link (~45-60 min; wasm-opt is the slow tail)
bash scratchpad/stage-jspi.sh                  # GL post-patches + validate -> play-gui/
```

`stage-jspi.sh` must run after every link. It applies the minified GL-glue
patches (`fc-post-weh.sh`), the material-colour patch, and the JSPI table
guard, then validates the wasm. It prints `VALID` on success — if it doesn't,
do not ship the artifact.

## Extra objects linked in

`weh-objs/` holds objects built outside cmake and passed to the link:

- `fcweb_dlg_module.cpp` — the `_fcwebdlg` Python builtin (blocking HTML
  dialogs via `EM_ASYNC_JS`, which is what lets a Python-triggered dialog
  suspend under JSPI and return the user's real click).
- `fcweb_export_stub.c`

```bash
em++ -fwasm-exceptions -pthread -O2 -I<python-include> -c fcweb_dlg_module.cpp -o weh-objs/fcweb_dlg_module.o
```

## Source patches

FreeCAD/CPython source lives in `deps/` (gitignored). The deltas are kept as
patches and must be applied to a fresh checkout:

- `patches/freecad.patch` — regenerate with `patches/regen.sh` after editing
  anything under `deps/src/freecad`.
- `deps/src/cpython/Python/emscripten_trampoline.c` — `_PyEM_detect_type_reflection`
  returns true when `Module.PyEM_CountArgs` exists, so CPython uses the
  reflection trampoline (a direct C call) instead of
  `_PyEM_TrampolineCall_JavaScript` (a JS frame JSPI cannot suspend across).
  Must be compiled with an explicit `-DPY_CALL_TRAMPOLINE=1` — the guard sits
  above the `#include <Python.h>`, so pyconfig.h's define never reaches it and
  a plain rebuild silently produces an empty 273-byte object.

**VTK is not a git checkout**, so `patches/regen.sh` skips it (its MAP only covers
freecad/pyside-setup/occt/cpython/numpy/coin3d). Its one delta is kept as a standalone
patch that must be applied by hand before configuring VTK:

```bash
patch -p1 -d deps/src/VTK-9.3.1 < patches/vtk-expat-wasm-xmlsize.patch
```

Without it, VTK's bundled expat compiles `XML_Index` as 32-bit (its own CMakeLists forces
`EXPAT_LARGE_SIZE=OFF` for Emscripten) while every consumer's `vtk_expat.h` declares the
same functions 64-bit. wasm is strictly typed, so `wasm-ld` turns that mismatch into a
trapping stub and **every `.vtu` parse dies with `RuntimeError: unreachable`**, taking the
caller with it — which silently aborted FEM document restore. If you ever rebuild VTK,
also refresh the installed copy of the header, since FreeCAD compiles against it:
`deps/wasm/include/vtk-9.3/vtk_expat.h`.

Gotchas that cost real time:

- **OCCT** `OCC_CONVERT_SIGNALS` uses `setjmp`; combined with wasm-EH in one
  function it emits invalid wasm (`br_table label arity`). Gated off for
  Emscripten in `occt_defs_flags.cmake` and salomesmesh's `CMakeLists.txt`.
- **shiboken** reimplements stable-ABI CPython functions (`pep384impl.cpp`).
  The linker would bind libpython's core init to shiboken's broken
  `PyStaticMethod_New` and segfault during interpreter startup; the definitions
  are `#define`-renamed under `-DFCWEB_REAL_CPYTHON`.
- Set `-DCMAKE_STRIP=/usr/bin/true`. Apple `strip` corrupts the archives and
  `emstrip` drops the symbol table.

## Editing FreeCAD's Python (a trap)

The link preloads `freecad-gui-install/Mod@/freecad/Mod`, **not** the source tree. So
editing `deps/src/freecad/src/Mod/**/*.py` changes nothing at runtime until you copy the
file into `freecad-gui-install/Mod/...` (or re-run the install) **and relink**, because
the `.py` files live inside `FreeCAD.data`. The symptom is silent: your patch is in the
source and in `patches/freecad.patch`, the feature just behaves as if you never touched
it. Check with:

```bash
diff deps/src/freecad/src/Mod/Fem/femmesh/gmshtools.py \
     freecad-gui-install/Mod/Fem/femmesh/gmshtools.py
```

## Meshing (gmsh) — a second wasm module

`configure-gmsh-weh.sh` + `build-gmsh-weh.sh` produce `play-gui/gmsh.{js,wasm}` (~28 MB),
fetched on first use so the main binary does not grow. It links the same wasm OCCT as
everything else, which is what lets gmsh `Merge` the `.brep` FreeCAD writes.

Two cross-compile gotchas, both already handled in the configure script:
- Do **not** pass `-DOCC_LIBS_REQUIRED=` — gmsh builds that list itself from the OCCT
  version and then `find_library`s each entry; overriding it to empty makes gmsh's count
  check silently disable OpenCASCADE (the build log then omits `OpenCASCADE` from
  "Build options", and `.brep` import is gone).
- emscripten's toolchain sets `CMAKE_FIND_ROOT_PATH_MODE_LIBRARY=ONLY`, so `find_library`
  ignores `CASROOT`/hints outside the sysroot. Needs `CMAKE_FIND_ROOT_PATH=$PREFIX` plus
  `..._MODE_LIBRARY=BOTH`.

FreeCAD reaches it through the `_fcwebgmsh` builtin (`fcweb_gmsh_module.cpp`, registered
in `MainGui.cpp`'s inittab, object in `weh-objs/`), which suspends via JSPI while the JS
side (`window.fcwebGmshRun` in `freecad-gui.html`) copies the `.geo`/`.brep` into the gmsh
module's separate filesystem, runs it, and copies the `.unv` back.

## Front-end

`play-gui/freecad-gui.html` is the app shell and **is** the served page
(`infra/nginx.conf` has `index freecad-gui.html`; `play-gui/index.html` is a
local convenience copy and is not deployed). `pre-gui.js` is inlined into
`FreeCAD.js` at link time via `--pre-js`, so changing it requires a relink —
or hot-patch the built `FreeCAD.js`, which contains the same code verbatim.

## Deploy

Artifacts are gitignored and shipped through a GitHub Release. The release
must exist **before** the branch push, because CI pulls the assets by tag.

```bash
gh release create build-YYYYMMDD-<slug> play-gui/FreeCAD.js play-gui/FreeCAD.wasm play-gui/FreeCAD.data
git push origin dev:ovhcloud     # triggers .github/workflows/deploy-ovh.yml
```

Verify live: `curl -sI https://freecad.virtastic.app/FreeCAD.wasm` — the
`content-length` must equal the local `play-gui/FreeCAD.wasm`.

## Relinking FreeCAD: two things the link does NOT do for you

1. **Re-apply the GL patches.** Two fixes live only in the linked `FreeCAD.js`, because
   they patch emscripten's generated GL-emulation code -- `pre-gui.js` is inlined
   *before* it, so they cannot go there. Every relink silently drops them:

   ```bash
   python3 tools/patch-freecad-js.py build-freecad-gui-weh/bin/FreeCAD.js
   ```

   Without it you get a boot-time storm of `Cannot read properties of null (reading
   '0')` from `getCurTexUnit`, and the 3D view never comes up. The script is
   idempotent and fails loudly if a patch site no longer matches.

2. **Check the .wasm size.** A correct link lands at ~152 MB. One link produced 234 MB
   with an exit status of 0 and nothing in the log -- `wasm-opt` had been skipped.
   Running it by hand afterwards is NOT equivalent to emcc's own post-link pipeline;
   relink instead.

### Known-broken: relinking from a clean tree

As of 2026-08-11 a relink of this tree reproduces a binary in which
`FreeCAD.newDocument()` never returns, while the shipped `build-20260810-gmsh`
artifacts work. This was isolated with `scratchpad/ccxe2e/probe.js`, which runs small
Python snippets one at a time:

| build | newDocument |
| --- | --- |
| release build-20260810-gmsh | works |
| relink + CalculiX bridge | hangs |
| relink, no CalculiX at all | hangs |
| relink, original .py files | hangs |

So it is the relink itself, not any particular change. The link inputs on disk are
unchanged since the release (no `.a` is newer), and `FreeCAD.js` is byte-identical to
the released one once the preload manifest and the GL patches are accounted for --
which points at the recorded link line in `scratchpad/linkcmds/` not being what
actually produced the release. **Resolve this before relinking for a release.**
