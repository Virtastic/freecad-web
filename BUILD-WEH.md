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

## Module coverage vs upstream FreeCAD 1.0

Every `BUILD_*` module is ON except **AddonManager**, which wants a `git` binary and
real sockets; the `.zip`/GitHub workbench installer covers that use case instead.
`BUILD_PLOT` and `BUILD_TEST` are ON -- Test's C++ half is the `QtUnitGui` module, which
needs both a `PyImport_AppendInittab` entry in `MainGui.cpp` and `QtUnitGui.a` on the
link line, since nothing is dynamically loaded. Plot ships no workbench class upstream,
so it is importable but correctly absent from the workbench list.

`INSTALL_TO_SITEPACKAGES` must be **OFF**. ON installs the `freecad` namespace package
into the *host* interpreter's site-packages -- a path a cross build usually cannot write
(the install then fails part-way, silently skipping the Gui/Doc install steps) and which
never reaches the wasm FS regardless. OFF puts it in `<prefix>/Ext/freecad`, the tree
preloaded as `/freecad/Ext`, so `import freecad` and `freecad.<addon>` layouts work.

Two Python packages are vendored into `deps/src/cpython/Lib` (preloaded as `/pylib`)
because FreeCAD needs them and they are pure Python: **ply** (`pip download ply`,
unzip the wheel) -- without it `importCSG` raises `No module named 'ply'` and OpenSCAD
import is dead. PySide6 ships Core/Gui/Widgets only; nothing in FreeCAD's own Python
imports the rest.

## Known: the one upstream test that hangs, and why it does not reach users

`Document.testApplyFiles` does not finish in 400 s (the other 107 tests in that suite
pass). Localised by driving one test per call (`scratchpad/onetest.js`) and then timing
the test's own steps: every step is 0.00 s up to and including the second `undo()`, and
it wedges on the first **`redo()`** of an `App::DocumentObjectFileIncluded` File
assignment, with the test's nested `openTransaction`s left uncommitted.

`PropertyFileIncluded` is not exotic -- TechDraw's SVG templates, hatches and images use
it, as do ArchSite/ArchBuildingPart -- so this was worth bounding rather than waving off.
The realistic path is clean: assigning an A4 template, switching it to A3, then undo x2
and redo x2 runs in <= 0.03 s per step. The hang needs the test's exact shape, so no
shipped workbench reaches it. Left unfixed and documented rather than guessed at.

(Two things ruled out along the way: `Base::Uuid` really does generate a fresh value per
construction, so `getUniqueFileName`'s `while (fi.exists())` -- which builds its uuid
once, outside the loop -- cannot spin; and `FileInfo::getTempFileName` uses `mkstemp`,
not a retry loop.)

## Workbenches that fail their FIRST activation

`Gui.activateWorkbench()` returns **False** when a workbench's `Initialize()` throws --
it does not raise. A probe that only catches exceptions therefore reports success while
the user clicks the workbench selector and nothing happens; the second click usually
works, because the failed Initialize left enough behind. Two shipped this way and were
found only by FreeCAD's own `Workbench.testActivate`, which walks every workbench:

- **CAM**: `No module named 'area'`. `libarea`'s Python module (`area.a`, `PyInit_area`)
  was built but absent from both the inittab and the link line, so `Path.Op.Adaptive`
  could not import and `Path.GuiInit.Startup()` threw. Cost 22 of CAM's 51 commands.
- **OpenSCAD**: `InitGui` calls `searchforopenscadexe()`, which shells out to
  `which openscad`; emscripten raises `OSError(138)` and takes Initialize down with it.
  Guarded on `sys.platform == "emscripten"` -- CSG import is pure Python and unaffected.

Two habits from this: after adding any statically linked Python extension, check it is
in **both** the inittab and the link line (`scratchpad/wbactivate.js` walks all 20
workbenches and prints each failure's traceback), and treat a False return as a failure
even when nothing was raised.

## FEM in the browser: never run its tasks on a thread

The solver framework (`femsolver/task.py`) and the mesh task panel
(`femtaskpanels/base_femmeshtaskpanel.py`) each ran their work on a worker thread --
`threading.Thread` and `QThread` respectively. Both reach the solvers through JS imports
owned by the **main** thread (`window.fcwebCcxRun`, `window.fcwebGmshRun`), and JSPI can
only suspend the main stack, so on a worker `_fcwebccx.available()` / `_fcwebgmsh
.available()` return False. The result was not an error but a wrong branch: Solve
reported *"The Calculix binary has not been found"* and meshing fell through to
`which gmsh`. **The Solve button and the mesh panel's Apply had therefore never worked**,
while every scripted CalculiX/gmsh test passed, because scripts call the tools directly
on the main thread. Both sites now run inline under `sys.platform == "emscripten"`.
The GUI entry point already did `machine.start(); machine.join()` synchronously, so
nothing became more blocking than it was. These were the only two Python threading
sites in the shipped tree -- check any new one against this.

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
# ALL SEVEN, always: CI hard-fails on a missing asset, and gmsh/ccx are separate
# wasm modules that a FreeCAD-only relink does not rebuild -- re-upload them unchanged.
gh release create build-YYYYMMDD-<slug> \
  play-gui/FreeCAD.js play-gui/FreeCAD.wasm play-gui/FreeCAD.data \
  play-gui/gmsh.js play-gui/gmsh.wasm play-gui/ccx.js play-gui/ccx.wasm
git push origin dev:ovhcloud     # triggers .github/workflows/deploy-ovh.yml
```

Verify live: `curl -sI https://freecad.virtastic.app/FreeCAD.wasm` — the
`content-length` must equal the local `play-gui/FreeCAD.wasm`.

## Installability, and why it is a data-safety feature

Chrome refuses `navigator.storage.persist()` on engagement alone -- measured, three
visits on one profile with real interaction each time, denied every time
(`scratchpad/persistgrant.js`). It grants it automatically to an **installed** app.
Without it the browser may evict a user's saved documents to reclaim disk space, so the
manifest, icons and service worker exist for that reason before any convenience one.

The service worker is a **pass-through and must stay one**. Chrome requires a fetch
handler for installability; ours never calls `respondWith`. The engine is 139 MB served
with exact `Content-Encoding` and cross-origin-isolation headers, and a caching worker is
an excellent way to corrupt that. It carries an `unregister` message handler as an escape
hatch. nginx serves it `no-cache` (the `.js` artifact rule would otherwise pin it
immutable for a year); Cloudflare's zone Browser Cache TTL still stamps 4 hours on it,
which is harmless for a no-op worker but means worker updates are not instant.

`/play-gui/*` is gitignored with an allowlist -- a new front-end file needs an explicit
`!` exception or the image builds without it and the deploy fails.

## The engine triple must be content-addressed together

`FreeCAD.js`, `FreeCAD.wasm` and `FreeCAD.data` are ONE artifact split across three
files: the JS carries the byte offsets of everything packed inside the data. They are
served `Cache-Control: immutable` for a year, so if any of them changes at a fixed URL a
returning browser mixes an old one with a new one. That is not hypothetical -- it shipped:
a cached `FreeCAD.js` plus new data meant CPython could not import its own `encodings`
module, and the app died on the splash with a Qt error dialog. First-time visitors were
completely fine, which is why every check missed it.

`infra/Dockerfile` now stamps all three URLs from their own md5 and fails the build if any
stamp is missing. The entry HTML is `no-cache` so those stamps are actually seen.

**Always run one gate with a REUSED browser profile.** `scratchpad/reg-prod.js` keeps a
fixed `userDataDir` deliberately -- it is the only harness that behaves like a returning
user, and it is the one that caught this. Fresh-profile testing cannot see a stale-cache
bug, an accumulating-state bug, or anything else that only exists on the second visit.

**When a harness says "0 page errors" but nothing works, take a screenshot.** The failure
here was a Qt modal sitting in the middle of the canvas the whole time; the console showed
only repeated `readobject called with exception set`.

## Releasing: the checklist, and the ways it bites

1. **Release first, push second.** CI pulls assets by tag, so the release must exist
   before the branch push.
2. **Re-run `tools/patch-freecad-js.py` after every link**, and check its exit status --
   it now verifies invariants, not just per-patch status. A relink plus that one tool
   reproduces the shipped `FreeCAD.js` byte for byte.
3. **Wait for the RIGHT workflow run.** Polling `gh run list --limit 1` right after a push
   matches the PREVIOUS run and reports success for a deploy that has not started. Capture
   the newest run id before pushing and wait for a different one to complete. This
   silently reported a green deploy of code that was not live.
4. **Verify the artifacts through the CDN, not locally** -- md5 what production actually
   serves against the local file. Only that catches an edge cache serving something else.
5. **Never hand-write a cache-busting version.** `FreeCAD.data.gz` is immutable for a
   year; the image stamps the URL with the data's md5 so changed data is a new URL
   automatically. A purge does not save you here: purge-by-URL must match the query
   string exactly.
6. **Beware probing a URL before it exists.** Cloudflare cached a 404 for `ccx.js` for a
   year, and later cached `FreeCAD.data.gz` from a probe made before nginx served it with
   `Content-Encoding` -- which would have broken every boot had the versioned URL not
   sidestepped it.

The gates worth running against production before announcing anything, all in
`scratchpad/`: `reg-prod.js` (workbenches, examples, dialog), `workflows.js` (eight real
CAD workflows), `guidrive.js` (menus and toolbars through Qt input), `datasafety.js`
(work survives a reload), `ccxe2e/run-prod.js` (FEM end to end), `prodcheck.js` (boot,
storage, bridges).

## Memory: the heap is a fixed 2 GB, deliberately

`-sINITIAL_MEMORY=2147483648 -sALLOW_MEMORY_GROWTH=0`. Growth was built and measured
(`scratchpad/linkcmds/fc-linkcmd-weh-grow.sh`, initial 1 GB / maximum 4 GB) and **not
shipped**, for a reason worth knowing before anyone tries again:

- With growth, emscripten can no longer hold a heap view across a grow, so every heap
  access in the JS glue becomes an accessor call: `GROWABLE_HEAP_F32()[x>>>2>>>0]`
  instead of `HEAPF32[x>>2]`. **841 sites** change form.
- That invalidates the hand-derived patch set in `tools/patch-freecad-js.py`, whose
  search text embeds the old form.
- emscripten warns about it directly: `-pthread + ALLOW_MEMORY_GROWTH may run non-wasm
  code slowly`. On this build the hot path IS non-wasm code -- Coin renders through the
  JS GL emulation, touching the heap per vertex -- and the heavy scene is already
  draw-call bound at ~11 fps.

So growth trades a permanent cost on the render path for a ceiling that measurement says
is not close: gmsh meshes a box to 77k nodes / 429k tets inside 2 GB. What the fixed heap
DID need was a civil failure, and it has one now: an out-of-memory abort says so in
words, instead of the app dying with nothing on screen.

If you do revisit it, re-derive every heap-touching patch for the accessor form first,
then A/B the render path before believing it is free.

## Reproducibility

Verified 2026-08-12: `scratchpad/linkcmds/fc-linkcmd-weh.sh` reproduces the shipped
binaries **byte for byte** -- `FreeCAD.wasm` md5 `01a524cd310ca88e31c6a5e44bc32e1b`, and
`FreeCAD.js` md5 `063d08a6fb27e2fb4993f600c6801e54` after `tools/patch-freecad-js.py`.
The recorded link line had gone stale (it predated CalculiX and was missing
`weh-objs/fcweb_ccx_module.o`, so it failed with `undefined symbol: PyInit__fcwebccx`);
that object is now in it.

## Relinking FreeCAD: three things the link does NOT do for you

0. **Rebuild `play-gui/FreeCAD.data.gz`.** The page loads the **gz**, never the raw
   `.data` (`freecad-gui.html`'s `locateFile`). A `.gz` left over from the previous link
   pairs the new JS with the old data, and CPython dies with *"Failed to import
   encodings module"* behind a Qt error dialog -- which reads as a broken build, not a
   stale file. `tools/sync-play-artifacts.sh` copies the triple, runs the JS patcher and
   regenerates the gz; use it instead of `cp`.


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

### Resolved: "relinking from a clean tree is broken"

Recorded here for a while as an unexplained defect -- a relink produced a binary where
`FreeCAD.newDocument()` never returned, while the released artifacts worked. It was not
the relink. A clean relink reproduces the release **byte for byte** (both the `.wasm`
and the `.data` md5 match). What the relink drops is the 27 hand-applied patches in
`FreeCAD.js`, which is what point 1 above is about; without them the GL emulation throws
during the first document's viewport setup and the call never comes back. Run
`tools/patch-freecad-js.py` after every link and there is nothing else to resolve.
