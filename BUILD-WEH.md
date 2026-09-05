# Reproducing the production build (wasm-EH + JSPI)

This is the lane that produces what runs on <https://freecad.virtastic.app>.
It is a **full-world rebuild**: everything must be compiled with wasm exceptions
(`-fwasm-exceptions`). Mixing in one JS-EH (`-fexceptions`) library silently
reintroduces `invoke_*` JS trampolines, and JSPI cannot suspend across a JS
frame — dialogs stop returning the user's real choice.

There is a second axis to that rule since emsdk 6.0.9. Wasm exceptions come in two
instruction sets -- the legacy `try`/`delegate` model, which is still the 6.0.9 default,
and the standardised `try_table`/`throw_ref` model, which `toolchain/env.sh` selects with
`-sWASM_LEGACY_EXCEPTIONS=0` for every compile and link. The setting changes object code,
wasm-ld links a mix without a word, and node validates it; Chrome refuses the module
("uses a mix of legacy and new exception handling instructions"). Link 33963711535 got
through every static gate and never started for exactly this: Coin3D, xerces-c and the
boost libraries had been built before env.sh set the flag and sat in a cache with a
literal key behind "already built, skipping" guards. `target_features` cannot tell the
two models apart (both say `+exception-handling`), so `tools/check-archive-eh.sh` reads
the opcodes: the deps lane prunes legacy archives before its build steps and refuses to
go green with any left, and the link preflight refuses to start on a mix. The link ccache
hashes env.sh, because emcc appends `EMCC_CFLAGS` itself and ccache never saw them.

## The dependency versions are not recorded — and that is the top reproducibility defect

Twenty-three dependencies are referenced by an **unversioned** path: `deps/src/occt`,
`deps/src/coin3d`, `deps/src/cpython`, `deps/src/freecad`, `deps/src/pyside-setup`, and so on.
Only two carry a version anywhere in the tree: `VTK-9.3.1` and `hdf5-1.14.3`.

So for twenty-one of them **the version is whatever happens to be on the build machine's
disk**. `deps/` is gitignored, so nothing else records it. That means:

- production cannot be reproduced by anyone else, or by this machine once those directories
  move on;
- "rebuild the dependencies in CI" is not merely slow, it is *undefined* — you would be
  building some OCCT, not the OCCT production was built from.

This is not hypothetical. It is exactly how CalculiX ended up with 69 routines silently
stubbed in a clean build while production's solver worked correctly: the build machine held
f2c workarounds nobody had captured, and nobody noticed until someone built from clean on
2026-08-16 (see `docs-ccx-stubbed-routines.md`). CalculiX was one instance of this defect.
The dependency stack is the general case, and it is still open.

**Fix, and it takes about a minute.** On the build machine, with `deps/` populated as it was
for the release:

```bash
bash tools/capture-dep-versions.sh > deps-versions.txt
git add deps-versions.txt && git commit -m "chore: pin the dependency manifest"
```

The script only reads — it clones nothing and changes nothing. It records a git commit where
a dependency is a checkout, a stated version where the tree declares one, and a content
checksum where it declares nothing, so even the `unknown` entries become comparable. After
that a clean rebuild has a target to hit and any drift is a diff rather than a mystery.

Until that file exists, treat every "reproduce the build" instruction below as
best-effort rather than exact.

## The FreeCAD C++ compiles clean on 1.1.3, all 29 modules (CI run 32262732636)

`build-freecad.yml` reached **2676/2676 targets, 0 failed** -- 2,215 objects and 30+ static
libraries: `libFreeCADApp.a`, `libFreeCADGui.a`, `libFreeCADBase.a`, plus Part, PartGui,
PartDesign, PartDesignGui, Sketcher, SketcherGui, Mesh, MeshGui, MeshPart, MeshPartGui,
Materials, MatGui, Points, PointsGui, Import, ImportGui, Measure, MeasureGui, Fem, FemGui,
DraftUtils, Spreadsheet, SpreadsheetGui, Start, StartGui, Surface, SurfaceGui, Inspection,
InspectionGui, Robot, RobotGui, ReverseEngineering, ReverseEngineeringGui, TechDraw,
TechDrawGui, PathApp, PathGui, PathSimulator, CAMSimulator and the SMESH stack.

Got there in two steps: 11 modules first (run 32247556806, 1699/1699), then widened to 29.
The widening was worth doing on its own -- it found four more defects that the narrower
build could not structurally have shown, including a `lineScaleFactor` call site that only
fails once TechDraw is actually compiled.

That is the first time anything other than the build machine has compiled this port, and
the first time it has been compiled at all against 1.1.3. It does **not** link -- see the
job's own header for why, and what the link still needs.

Read the scope honestly:

- **Compiled, not linked.** The final binary additionally needs PySide6, shiboken, pivy,
  IfcOpenShell, numpy, matplotlib, `_ctypes`, Pillow, and the gmsh and CalculiX modules.
  None of those are in the dependency cache, and none of them change whether the port's
  C++ is correct.
- **Two modules still off**, and not for want of trying: Assembly needs the OndselSolver
  submodule and AddonManager *is* a submodule, and GitHub source tarballs carry no
  submodules. Everything else the dependency cache can satisfy is on.
- **Compiling is not running.** Nothing here exercises the GL emulation, the JSPI shims or
  the 3D viewport. `gl_compat.h` is proven consistent and proven to build Coin3D and all of
  FreeCADGui; it is not proven to render a pixel.

What it does establish: `patches/freecad.patch` applies at zero fuzz to a pristine 1.1.3
tree and every one of its hunks compiles, on a machine that is not the build machine, from
a clean checkout.

## The Python extension libraries now build in CI (run 32280917492)

Nine archives, all verified by name rather than by exit status:

| | |
|---|---|
| numpy 2.1.3 | 19 archives; `_multiarray_umath`, `_pocketfft_umath`, `_umath_linalg`, `lapack_lite` |
| matplotlib 3.9.2 | 13 archives (8 extensions + freetype, qhull, agg, ttconv) |
| kiwisolver 1.4.7 | `libkiwi__cext.a` |
| Pillow 10.4.0 | `libpil__imaging.a` |
| libffi + `_ctypes` | `libffi.a`, `lib_ctypes.a` |
| pivy 0.6.9 | `lib_coin.a` -- `PyInit__coin` |
| IfcOpenShell 0.8.0 @481676e5 | `lib_ifcopenshell_wrapper.a` + IfcParse/IfcGeom/Serializers, 358/358 targets |

Those versions are now **pinned in `build-python-deps.yml`** -- along with pivy, IfcOpenShell (to a commit, since 0.8 has no tag), its `svgfill` submodule, Eigen 3.4.0 and SWIG 4.2.1. Nine fewer entries on the list of dependencies whose version is "whatever is on the build machine's disk", and SWIG in particular was silently deciding whether the build worked.

Getting there took eight defects, none of which a passing script would have revealed:

1. `configure-numpy.sh` **did not exist** — referenced by name in two tracked scripts and
   never committed. Reconstructed from its consumers.
2. `configure-matplotlib-weh.sh` globbed `*.cpython-313-darwin.so.p`, so anywhere but
   macOS it harvested **nothing** and produced an empty `mpl-mod`.
3. numpy declares Cython as a *compiler* in its `meson.build`.
4. numpy needs the **meson fork it vendors**; `import('features')` exists nowhere else.
5. `sysconfig` reported host values — fixed with `_PYTHON_SYSCONFIGDATA_NAME`.
6. That fixed reporting but not include ORDER: meson puts the host CPython build tree
   ahead of the wasm one, so the 64-bit `pyconfig.h` won. Both meson builds (numpy,
   matplotlib) hit it; the three hand-compiled lanes never could.
7. matplotlib's freetype subproject 502s from savannah; seeded from a mirror, hash checked
   against the `.wrap`.
8. libffi's `LT_SYS_SYMBOL_USCORE` is **not shipped by this libtool at all** — three
   rounds went into the macro search path before a diagnostic showed the macro simply does
   not exist here. Supplied directly at the time. Superseded: libffi now comes from the
   upstream 3.8.0 release tarball, which ships a generated `configure` (no autogen, no
   libtool macros) and carries the wasm64 target the hoodmane fork never had.

The lesson worth keeping is #8's shape: the error named a symptom (`possibly undefined
macro`) and every fix aimed at the wrong cause until something printed what was actually
installed.

## FreeCAD 1.1.3 needs four things 1.0 did not

Established by getting `build-freecad.yml` to configure, one error at a time. Anyone doing
the full link needs all of these, not just the compile job.

| | |
|---|---|
| **ICU** | `find_package(ICU REQUIRED COMPONENTS uc i18n)` is now at the top of FreeCAD's `CMakeLists.txt`, and ICU is linked into `Base`. 1.0 had no ICU dependency at all. emscripten ships a port (`--use-port=icu`; built by compiling a probe through emcc, never `embuilder`, which ignores the toolchain and builds wasm32 -- `tools/check-toolchain-env.py` refuses it), so no cross-compile is needed -- but it names the libraries after ICU's source directories (`libicu_common`, `libicu_i18n`, `libicu_stubdata`) rather than the usual `libicuuc`/`libicui18n`/`libicudata`, so CMake's own `FindICU` finds the headers and then reports the components missing. `toolchain/cmake/FindICU.cmake` replaces it. Note the port is **stubdata** -- no locale data, which is right for a browser but rules out real collation. |
| **Eigen ≥ 3.4** | Header-only, and the dependency stack never built it: `deps/wasm/include` contains no Eigen, which is why `FindEigen3` reported an empty version and refused. |
| **SWIG** | `SetupSwig.cmake` FATAL_ERRORs whenever `BUILD_SKETCHER` is on, then runs `swig -python -external-runtime` to check its runtime version against pivy's. Host tool; `pip install swig` avoids needing root. |
| **A threaded Qt** | Not new in 1.1, but 1.1 is what exposed it. FreeCAD lists `Concurrent` among its four base Qt components, and QtConcurrent requires the thread feature. Qt for WebAssembly defaults to **single-threaded**, and `build-qt-wasm.yml` never passed `-feature-thread` -- so the Qt cached under `qt/6.11.2/wasm_mt_weh` was, despite the name, a single-threaded build with no QtConcurrent in it. Everything else here is compiled `-pthread`, so that artifact was wrong regardless. |

Already handled by `patches/freecad.patch`, and worth knowing before someone re-derives it:
the bundled SMESH path does `find_package(MEDFile REQUIRED)`, which the port replaces with
an `if(EMSCRIPTEN)` branch wiring `deps/wasm`'s static HDF5 in directly -- the wasm build
compiles no DriverMED sources, only headers.

## Toolchains

| Path | Version | Used for |
|---|---|---|
| `emsdk/` | 6.0.9 (pinned) | all compiling and linking |

Pinned in `toolchain/env.sh`, which is the ONLY place the SDK and the target are set.
It exports `EMCC_CFLAGS=-m64` and then asserts `__wasm64__` is defined before any build
runs -- emcc appends `EMCC_CFLAGS` to every invocation, including the probe compiles
autotools and meson run during configure, which is what keeps a configure test from
measuring wasm32 sizes and baking them into a wasm64 build.

`tools/check-toolchain-env.py` fails CI if any script reaches `emcc` without sourcing it.
That gate exists because fifteen scripts once sourced `emsdk/emsdk_env.sh` directly -- the
whole CalculiX/gmsh stack and most of the Python extension stack -- along with the shipped
link command, which called `em++` by absolute path.

**The `emsdk2/` wasm-opt shim is gone.** It existed because emsdk 3.1.70 shipped binaryen
v119, which could not parse wasm-EH, so `wasm-opt` was shimmed to a 4.0.23 binary and every
link printed `unexpected binaryen version: 125 (expected 119)`. 6.0.9 carries a binaryen
that parses its own output, so both the second SDK and that warning are history.

**Why 6.0.9 and not a Qt-sanctioned emscripten.** Qt for WebAssembly pins one emscripten
per Qt minor: Qt 6.9 pinned 3.1.70 (which is why this project sat there for so long) and
Qt 6.11 pins 4.0.7. But wasm64 with pthreads and a `MAXIMUM_MEMORY` above 4 GB is only
fixed in 5.0.1/6.x (emscripten#26311, PR #26357), and the pthread mailbox gap is
emscripten#21159. Both pins cannot be honoured at once, so Qt 6.11.2 is deliberately built
on an emscripten it has never been validated against. Expect to carry Qt patches.

## The three force-included headers (read this before anything else)

Every build script below passes `-include $DW/include/gl_compat.h`, and the FreeCAD ones add
`-include $DW/include/coin_intrusive.h`. A third, `qprocess_stub.h`, is force-included into
all of FreeCADGui by `src/Gui/CMakeLists.txt` (added by `patches/freecad.patch`):

| header | what it supplies |
|---|---|
| `gl_compat.h` | the legacy fixed-function GL declarations Coin3D and FreeCAD compile against on a GLES/WebGL2 target |
| `coin_intrusive.h` | the `boost::intrusive_ptr` adapters for `SoBase` (a from-source Coin lacks them; the definitions are in `patches/freecad.patch`, in `SoFCDB.cpp`) |
| `qprocess_stub.h` | an inert `QProcess`, because Qt-for-WebAssembly has no subprocesses — the external-tools, graphviz, help and network paths compile against it as no-ops |

**None was tracked in this repository until 2026-08-18, and this document never mentioned
them.** They existed only on the build machine, under the gitignored `deps/` path, so nothing
produced them and the failure arrived as an inscrutable compile error a long way from the
cause.

**How much this actually blocks, measured rather than assumed.** CI run 32099719534 built
Coin3D to completion against an **empty** `gl_compat.h` — `libCoin.a`, 11,785,732 bytes, zero
compile errors. So Coin does *not* need it, and the whole C++ dependency stack (boost,
xerces-c, OCCT, VTK, Coin3D) now builds on a hosted runner from a clean checkout. What remains
untested is the **FreeCAD** build, which force-includes the header into every C and C++
translation unit and calls the legacy GL entry points that `gl_legacy_stubs.c` defines — those
need declarations from somewhere. Do not read "Coin built" as "the header is unnecessary";
read it as "the blocker is narrower than it looked, and sits at the FreeCAD link, not before".

That is the CalculiX defect again: uncaptured build-machine state, invisible because the path
is gitignored. Treat it the same way.

**All three are now reconstructed and tracked in `toolchain/include/`**, so a clean checkout
no longer stops here.

- `coin_intrusive.h` — signatures dictated by the definitions in `patches/freecad.patch`,
  so any correct version is equivalent to the original.
- `gl_compat.h` — **generated**, not hand-written: `tools/gen-gl-compat.py` reads
  `gl_legacy_stubs.c` and emits a declaration for each of the 58 entry points it defines.
  That file exists precisely because emscripten's `LEGACY_GL_EMULATION` does not provide
  them, so it *is* the specification. Keeping the two mechanically linked means a stub
  without a declaration is a compile error and a declaration without a stub is a link
  error, instead of the two drifting. Regenerate rather than editing:

  ```bash
  python tools/gen-gl-compat.py > toolchain/include/gl_compat.h
  ```

  The one symbol it omits is `fcwasm_draw_text_tris`, which `patches/coin3d.patch`
  declares at its own call site.
- `qprocess_stub.h` — an inert `QProcess`. Derived from every member the tree actually
  calls, cross-checked against all five consumers. It has **no `Q_OBJECT` and no signals**,
  because a header force-included into hundreds of translation units cannot be run through
  moc — which is why `patches/freecad.patch` `#if`s out every `connect()` to a `QProcess`
  signal. It does derive from `QObject`, since `kill()` is used as a slot. Verified: every
  signal `connect` and the one `QTextStream(proc)` sit inside a wasm guard.

These are RECONSTRUCTIONS and have **not yet been through a FreeCAD compile** — that is the
next thing to prove. If the build machine's originals are still available they remain the
reference; capture them and let `stage-headers.sh` diff the two:

  ```bash
  bash tools/capture-build-machine-headers.sh
  git add toolchain/include && git commit
  ```

`toolchain/stage-headers.sh` copies the tracked headers into `$DW/include` and refuses to
continue if one is missing, naming it. The build machine's copy always wins: an existing
header is never overwritten by a reconstruction, only diffed against it. The Coin and FreeCAD
configure scripts call it, so this is automatic.

Until `gl_compat.h` is captured, `.github/workflows/build-deps.yml` builds Coin in
**diagnostic mode** — an empty header — and prints any undeclared identifiers the compiler
reports, which would be the header's specification. As of run 32099719534 that list is empty
because Coin compiles cleanly without it. The same mechanism is what will produce the
specification for the FreeCAD build, where the header is expected to matter.

Objects built this way are still **not production-equivalent**: they were compiled against a
different set of declarations from the ones the shipped binary saw. Nothing built in
diagnostic mode may be linked into a release.

## Order

Dependencies first — each must finish before the next starts.

```bash
bash toolchain/stage-headers.sh    # the force-included headers; fails loudly if one is missing
bash build-boost-weh.sh            # boost
bash build-xercesc-weh.sh          # xerces-c
bash configure-occt-weh.sh         # OCCT   (gates OCC_CONVERT_SIGNALS off, see below)
bash configure-vtk-weh.sh          # VTK
bash configure-coin-weh.sh         # Coin3D
bash deps-weh-lane2.sh             # yaml-cpp, etc.
bash configure-kiwisolver-weh.sh
bash configure-matplotlib-weh.sh   # uses matplotlib-crossfile.meson
bash configure-ifcopenshell-weh.sh
bash rebuild-pyside-weh.sh         # shiboken6 + PySide6
bash pyside-finish-weh.sh
bash lane4-weh.sh; bash lane5-weh.sh
```

Qt 6.11.2 is built from source into `qt/6.11.2/wasm_mt_weh` with
`-feature-wasm-exceptions -feature-wasm-jspi`.

**This now builds in CI** — `.github/workflows/build-qt-wasm.yml`, **56 minutes** on a hosted
ubuntu-latest runner (run 32041786072), installing to that exact prefix. Not 2–3 hours, which
was my estimate before measuring.

The trick is that cross-compiling Qt needs a *host* Qt to run `moc`/`rcc`/`uic`/`qsb`, but
only the **target** needs the two features above. The host never touches wasm, so it can be an
ordinary `aqtinstall` prebuilt, which removes an entire Qt build from the critical path.

Three things had to be right, each found from a build log rather than guessed:

1. **The host needs `qtshadertools`.** `qtdeclarative` depends on it and its `qsb` shader
   compiler runs on the host. Without it configure dies with *"Qt6ShaderToolsTools package
   could not be found"*. The rule: a host Qt needs every module whose **tools** the build
   runs — not the target's module list.
2. **Only `qtshadertools` is a separate `aqtinstall` module** for 6.11.2. `qtdeclarative`,
   `qtsvg` and `qttools` live in the base `linux_gcc_64` package, and naming them makes `aqt`
   fail outright so no host Qt is installed at all.
3. **The runner needs desktop runtime libraries.** `qsb` is a dynamically-linked Qt Gui binary
   even though it only compiles shaders offline, so a bare runner fails at
   *"libEGL.so.1: cannot open shared object file"* — 731 targets into the build.

Then FreeCAD itself:

```bash
bash configure-gui-weh.sh                      # cmake configure -> build-freecad-gui-weh
cd build-freecad-gui-weh && ninja              # ~1h cold
bash scratchpad/linkcmds/fc-linkcmd-weh.sh     # link (~45-60 min; wasm-opt is the slow tail)
bash scratchpad/stage-jspi.sh                  # GL post-patches + validate -> play-gui/
```

**`stage-jspi.sh` can report `mat:MISS` and still exit 0.** Its material-colour regex only
matched an else-branch of `{0}`; the 2026-09-04 link emitted
`{throw"glMaterialfv: TODO: "+pname}` instead, so the patch silently did not apply and the
staged `FreeCAD.js` came out without a fix the shipping artifact had. The link succeeded,
the size was right, and only a byte comparison against the live file showed it. Two other
traps in the same run: `scratchpad/wasmvalidate.js` was absent, so the `VALID` check never
ran at all, and `fc-post-weh.sh` died on a missing `play/server.py` after doing its work --
`stage-jspi.sh` swallows that with `|| true`.

So after staging, verify rather than trust the exit status:

```bash
python3 tools/patch-freecad-material.py play-gui/FreeCAD.js   # tracked; matches either form
python3 tools/patch-freecad-js.py play-gui/FreeCAD.js --check
```

The material patch is now tracked as `tools/patch-freecad-material.py` precisely because
living only in `scratchpad/` is how it came to be lost.

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

## The 2 GB heap: measured, and now warned about before it bites

`ALLOW_MEMORY_GROWTH=0` with `INITIAL_MEMORY=2GB`, so the heap is PRE-ALLOCATED and
`HEAPU8.buffer.byteLength` reads 2048 MB from boot -- it is the ceiling, not the usage, and
any "heap used" probe built on it is meaningless. The used portion is the sbrk break, so
`_emscripten_get_sbrk_ptr` is now in `EXPORTED_FUNCTIONS`. Reading it from JS is a plain
memory read: no Python, no round trip, and it works **while the interpreter is busy** --
which is exactly when memory is being consumed, and exactly what defeated two earlier
attempts to measure this (one wedged behind a 3D view rebuild, the other pegged a renderer
thread for 20+ minutes with no answer).

Measured on this build:

| state | heap used |
|---|---|
| after boot | **288 MB** |
| empty document | 288 MB |
| 800 simple solids | 322.8 MB |
| 1600 simple solids | 402.7 MB |

So roughly **72 KB per solid**, and the ~1.76 GB of headroom is on the order of **20,000
such solids**. Quote that rather than "there is a hard wall".

`freecad-gui.html` polls it every 5 s and, at 80% and again at 92%, FORCE-SAVES the user's
documents and says so in plain words. The point is the save, not the message: the abort
that follows is unavoidable, but the work no longer goes with it. Thresholds are
overridable via `window.__fcwebMemWarn` / `__fcwebMemCrit` so the behaviour can be tested
without building a 1.6 GB model -- **do not** test it by faking `HEAPU8.buffer`, which the
emscripten glue uses everywhere and which produces a cascade of aborts that looks exactly
like the feature failing.

## Timing anything: check the load average first, and diff the binary

A relink that added ONE export appeared to slow the BIM example from 6.2 s to 10.2 s --
about 50%, reproduced across several runs, and confirmed "independently" against
production. All of it was wrong:

- The two "independent environments" were local Chrome and production Chrome **running on
  the same machine**. Only the server differed. That is not independence.
- The load average was **25.8** during the slow readings (this box was linking, running
  memory experiments and holding a dozen leftover Chrome profiles). At load ~6 the same
  build opens BIM in 7.6 s; early in the session, on an idle box, 6.2 s.
- The two binaries differed by **37 bytes** -- the export entry. No mechanism exists for
  that to cost 50%.

Before believing a performance change: `uptime` (this project's builds routinely push the
load past 20), `ls -la` both wasm files (a 37-byte diff is not a regression; a 234 MB vs
152 MB diff means wasm-opt did not run), and A/B back-to-back under the same conditions --
never against a number measured hours earlier under different load.

`tools/sync-play-artifacts.sh` now refuses a wasm over 200 MB, because killing a link
mid-way leaves the un-optimized 234 MB intermediate in `bin/` looking finished, and
shipping that IS a real, large regression.

## Keyboard: Qt only hears keys while a TEXT widget has focus

The single most user-visible defect found in this port, and it hid behind the fact that
typing always worked. Measured with an application-wide Qt event filter:

| focus | what Qt receives |
|---|---|
| `QLineEdit` (any text widget) | everything -- Delete, Meta, Z |
| model tree (or any non-text widget) | **nothing at all** |

So **Delete did not delete** (`Std_Delete` is enabled and works when invoked via
`Gui.runCommand`), **Ctrl/Cmd+Z did not undo**, and no single-key shortcut fired. Qt-wasm
focuses a hidden DOM input only for text widgets; otherwise `document.activeElement` is
BODY and the keydown never enters Qt. The Escape-with-a-popup case above is the same bug.

Re-dispatching the identical `KeyboardEvent` onto **Qt's own canvas** (inside its shadow
root) does drive Qt, so `freecad-gui.html` forwards there rather than hard-coding a
shortcut table -- every key keeps whatever meaning FreeCAD gives it. Two properties matter
and are tested (`scratchpad/keyfix.js`):

- `isTrusted` is the loop guard. The forwarded copy is synthetic, so it is ignored by the
  same listener and cannot bounce.
- Forwarding is skipped when a text field has focus, or every character would arrive
  **twice**. Verified: typing `abc123` yields exactly `abc123`.

Verified end to end: Delete deletes, Cmd+Z restores, typing is not doubled, Escape still
closes menus, regression 8/8 + 6/6 with 0 page errors.

## JSPI: only the promising exports may suspend, and Qt's events were not among them

The deepest defect in this port, and it was invisible to every test that used the Python
bridge. Under `-sJSPI` only the exports listed in `ASYNCIFY_EXPORTS` are wrapped in
`WebAssembly.promising`, and **only a promising stack may suspend**. The link listed one:
`fcweb_run_python`. So anything driven from Python could suspend -- and every modal dialog
"verified" so far was triggered by `Gui.runCommand` through exactly that bridge.

Qt's own events take another route entirely: the browser calls
`Module.QtEventListener.handleEvent` (`qstdweb.cpp:743-751`), an embind method that is not
promising. Any nested event loop entered from real input therefore threw
`SuspendError: trying to suspend without WebAssembly.promising` -- and, because the
exception unwinds out of the handler, the action simply never happened:

| interaction (real mouse) | what a user saw |
|---|---|
| Help > About, Preferences, any message box | no dialog opens at all |
| drag a tree item onto a Group | nothing is reparented |

Both are nested loops: `QDialog::exec`, and `QDrag::exec` (`qwasmdrag.cpp:94-99` -- Qt only
attempts its wasm drag when JSPI is present, so this path exists *because* of JSPI).

The fix is one export and one JS class:

- `wasm_event_dispatch.cpp` exports `fcweb_dispatch_event(uintptr_t handler)`, added to
  **both** `EXPORTED_FUNCTIONS` and `ASYNCIFY_EXPORTS` (emscripten wraps it in
  `WebAssembly.promising` for us).
- `pre-gui.js` replaces `Module.QtEventListener` at `onRuntimeInitialized` -- after embind
  has registered its classes (initRuntime ran the ctors) and before `main` creates any
  listener. Qt's registration is `val::module_property("QtEventListener").new_(ptr)`, so a
  plain JS class with a `handleEvent` method is a drop-in.
- The event value crosses through `Module.__fcwebEvent` instead of an embind handle, so
  the JS side needs no access to emscripten's minified `Emval` internals. It is read
  synchronously before anything can suspend, so an event delivered *during* a suspend
  (which is the point -- a modal dialog keeps processing input) cannot clobber it.

If the export is missing (older binary), the shim leaves Qt's own listener alone: dialogs
and drag stay broken, but input keeps working.

## Getting work out: two save paths, and only one is scriptable

`File > Save` and `File > Export` clicked for real both deliver a file
(`scratchpad/filemenu.js`): `SaveMe.FCStd` 4203 B and `SaveMe-Brick.3mf` 1283 B landed on
disk, 0 page errors. The patched save dialog hands FreeCAD a staging path under
`/home/web_user/_dl`, and the watcher in the shell delivers it once written.

There are two delivery paths, and the difference matters when testing:

- **`showSaveFilePicker` (Chromium)** — the preferred one. It opens a **native OS dialog**
  that no script can answer, so an automated save just waits on a picker that never
  resolves: no download, no error, and `Document.FileName` still shows the `_dl` staging
  path. That is not a defect, it is a human-only path. A first run read exactly like a
  broken save.
- **anchor download (Firefox/Safari, or Chromium with the picker removed)** — scriptable,
  and what the harness exercises: `delete window.showSaveFilePicker` before clicking.

## Serving the app locally: python -m http.server cannot do it

`scratchpad/testserver.js` is the local server (port 8792 by convention). Python's
`http.server` is **single-threaded**, and the app fetches `FreeCAD.wasm`, `FreeCAD.data.gz`
and the pthread workers in parallel -- so the requests queue behind each other and boot
sits at "loading…" forever, with **no page error and no failed request** to explain it.
That looks exactly like a broken build. It cost three "failures" of `datasafety.js`, which
defaults to port 8791, before I checked which process was actually listening
(`lsof -nP -iTCP:8791 -sTCP:LISTEN`). Byte-for-byte the two servers were serving identical
files.

## Driving the GUI with real input, and how the harness lies to you

The keyboard defect was invisible to every scripted-API test, so each ordinary
interaction is now driven with real mouse and key events. All of these pass, with 0 page
errors (`scratchpad/pick3d.js`, `propedit2.js`, `dragdoc.js`, `moreinput.js`, `wheeldbl.js`):

| interaction | evidence |
|---|---|
| click a solid in the 3D view | selects it; clicking empty space clears; hover preselects |
| rubber-band select (`Std_BoxSelection` + drag) | both solids selected |
| wheel zoom | camera height 17.3 -> 2.3 |
| double-click a tree item | the task editor opens |
| arrow keys in the tree | current item moves A -> B |
| type a dimension in the property editor | `Length` becomes 42.000 |
| F2 rename in the tree | `Label` becomes `Renamed` |

Two harness traps burned a run each; check both before believing a failure:

- **Aim with FreeCAD's own projection.** Guessed click offsets found nothing and looked
  like broken picking. `view.getPointOnScreen(x,y,z)` gives the exact pixel -- but its
  origin is **bottom-left**, so flip Y against the subwindow height before clicking.
- **Raise the Model dock first.** The tree and the property editor are tabbed together;
  if that tab is not current, `isVisible()` is false for both and every lookup returns
  "not locatable" -- which reads exactly like the panel being broken.

## Escape and the popup keyboard grab

Escape now dismisses an open menu, and the route there is worth keeping because the
obvious fixes do not work. Measured on this Qt-wasm build:

- Typing reaches Qt normally: a focused `QLineEdit` receives real key events verbatim,
  even though `document.activeElement` is `BODY` and the Qt canvas has no `tabindex`.
- With **no** popup open, an event filter sees `Key_Escape` (16777216) arrive.
- With a popup open, the key never enters Qt's event system at all -- an application-wide
  filter installed on `QApplication` does **not** see it. The popup never gets the
  keyboard grab it has on desktop.

So this cannot be fixed from inside Qt, and a Python-level event filter (tried, verified
ineffective) is the wrong layer. `freecad-gui.html` watches for Escape in the DOM and
calls `closeActivePopup()`, which asks Qt to close `activePopupWidget()`. It is a no-op
unless a popup is actually open, so Escape keeps its normal meaning everywhere else, and
it respects `__fcPyBusy` so it can never re-enter a running interpreter.

Front-end only: no relink, and the release assets are unchanged -- push the branch and CI
rebuilds the image around the same release.

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
git push origin main:ovhcloud    # triggers .github/workflows/deploy-ovh.yml
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

## The engine was never actually cached, and the HTTP cache cannot fix it

The boot screen promised "first load downloads ~150 MB, then it is cached". It was false on
every visit. Measured against production, reloading in the **same** profile:

| asset | size | delivery on reload |
|---|---|---|
| `FreeCAD.js` | 1 MB | `deliveryType: "cache"`, transferSize 0 |
| `FreeCAD.wasm` | 152 MB (53 MB on the wire) | **`"network"`, 51 s** |
| `FreeCAD.data.gz` | 262 MB (63 MB on the wire) | **`"network"`, 58 s** |

The 1 MB file is the control: HTTP caching works fine in that profile. Chrome's disk cache
simply will not retain entries this large, and `Cache-Control: immutable` does not change
that. So every visit cost ~113 MB and 2–3 minutes — cold boot 171 s to READY, warm reload
115 s.

**Cache Storage has no such per-entry ceiling.** Measured before writing any of it: a single
152,506,718-byte entry stores in 409 ms and reads back in **111 ms**, byte-identical (wasm
magic `00 61 73 6d` intact), against a ~5 GB origin quota. Verified again through the real
implementation against the live asset: cold 2237 ms with 1366 progress callbacks, warm
**105 ms**, bytes identical, and a planted `?v=STALEBUILD` key correctly swept.

Three things that are easy to get wrong here:

- **Store a synthetic `Response`, never the network one.** `FreeCAD.data.gz` is served with a
  hand-set `Content-Encoding: gzip` over a body the browser has *already* decoded. Caching
  the network `Response` risks carrying that header onto non-gzip bytes — a double-decode on
  read, which is exactly the corruption this file warns about elsewhere.
- **Do not put it in the service worker.** `sw.js` is a pass-through on purpose; a
  fetch-intercepting worker sits in front of the precise `Content-Encoding` and
  cross-origin-isolation headers the whole boot depends on.
- **`content-length` is the wrong progress denominator.** Both assets are gzip-encoded in
  transit, so it reports the *compressed* size while the stream yields decoded bytes — the
  bar runs to ~300%. `freecad-gui.html` uses nominal decoded sizes instead.

The data package is handed to emscripten through `Module.getPreloadedPackage(name, size)`, a
documented hook already present in the shipped `FreeCAD.js` — so this needs no relink and no
addition to `tools/patch-freecad-js.py`. Returning `null` falls back to emscripten fetching
the URL itself, so a prefetch failure degrades to the old behaviour rather than breaking boot.

Cache keys are the stamped `?v=` URLs, so a new build is automatically a new key and anything
else is swept on boot. A damaged entry would otherwise be sticky forever, so a non-OOM abort
offers "clear cached engine and reload" (`window.fcwebClearEngineCache()`).

**Measured live on production after deploying it**, from a cleared cache:

| | before | after |
|---|---|---|
| first visit to Ready | 171 s | 23 s |
| return visit to Ready | 115 s | **8 s** |
| bytes fetched on a return visit | 113 MB | **0** |

`performance.getEntriesByType('resource')` shows **no entry at all** for `FreeCAD.wasm` or
`FreeCAD.data.gz` on the second load — they never reach the network. That is the check worth
re-running: it is the exact measurement that exposed the original defect.

## The nine "silently dead" GL calls: measured, and smaller than it looked

`tools/patch-freecad-js.py` rewrites nine fixed-function `throw"gl*: TODO"` sites to `0`.
That was correct — a throw unwinds through Coin's render traversal and takes the viewport
with it — but it left an unmeasured parity claim, because `glMaterialfv` and `glLightfv` are
how Coin sets material colour and lighting. "Silently does nothing" could have meant
"shading differs from desktop".

Instrumented (each `0` became a counter that still evaluates to `0`) and measured on
production:

| exercised | result |
|---|---|
| boot | no counter fired |
| box + cylinder + boolean fuse, shaded, isometric, fitAll | no counter fired |
| five camera changes (front/top/right/iso, fitAll) | no counter fired |
| **BIMExample — 361 objects**, heap 285 → 425 MB | **no counter fired** |

`window.__fcglNoop` stayed `undefined` throughout.

**Reading the code explains why, and it reframes the whole concern.** These `{0}`s are not
"the function does nothing". They are of two kinds:

- **Fallback branches for unhandled arguments** — `glLightModelf`, `glLightModelfv`,
  `glLightfv`, and `glMaterialfv`'s face check. The functions *are* implemented for the
  cases Coin actually uses, and the `glMaterialfv: EMISSION and AMBIENT_AND_DIFFUSE` patch
  extended them further. The `0` runs only for arguments emscripten never implemented, and
  nothing above reached one.
- **Genuinely empty functions** — `glTexCoord4f`, `glTexGenfv`, `glTexGeni`. The entire body
  is `{0}`. These are texture-coordinate generation, which only matters for texture-mapped
  materials; none of the above uses them.

So the honest status: for ordinary solid modelling and the heaviest bundled scene, the
no-ops cost nothing observable. What remains untested is texture-mapped materials, which is
where `glTexGen*` would finally be called — worth a targeted check before claiming full
parity, but it is a narrow gap rather than a broad one.

One counter is deliberately absent. `glMaterialfv`'s *pname* fallback anchors inside the
EMISSION patch's replacement text, and instrumenting it breaks that patch's already-applied
detection — the deploy caught this and refused. The selftest now asserts no counter anchors
inside any patch's replacement, so the class cannot come back.

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

## Memory: 16 GiB on wasm64 (supersedes both sections below)

**Status 2026-09-04:** this is a `wasm64-emscripten` build. The shipped link is
`-sINITIAL_MEMORY=1073741824 -sMAXIMUM_MEMORY=17179869184 -sALLOW_MEMORY_GROWTH=1` --
1 GiB growing to 16 GiB, which is where V8 caps wasm64 memory.

The thing that actually changed is not the number. Under wasm32 the ceiling was an
ARCHITECTURAL limit and the section below spends most of its length on the hazard that came
with approaching it: above 2 GB a pointer exceeds `INT32_MAX`, so any C++ in OCCT, Coin, Qt
or CPython holding a pointer in a signed `int` breaks -- plausibly as corrupt geometry
rather than a clean crash. **That entire hazard class is gone.** Pointers are 64-bit; no
reachable heap address comes near the signed boundary of the type holding it. The ceiling is
now policy, not physics.

The ceiling is stated in three places and they must agree, because the browser cannot ask
the module what its real maximum is (emscripten keeps the `Memory` object closure-private
and `Module.wasmMemory` is not set here):

| Where | What |
|---|---|
| `scratchpad/linkcmds/fc-linkcmd-weh.sh` | `-sMAXIMUM_MEMORY=17179869184` |
| `configure-gui-weh.sh` | `FCWEB_HEAP_MAX_BYTES` default |
| `play-gui/freecad-gui.html` | `var FCWEB_HEAP_MAX_BYTES` |

`tools/check-link-settings.py` fails CI when they drift. If they do, nothing breaks loudly:
the memory-pressure monitor computes `used/cap` against the wrong cap and force-saves at the
wrong moment, or never -- and that feature exists precisely to save the document just before
an unavoidable abort.

One caveat carried forward from the toolchain notes: emscripten had a bug where MEMORY64 +
pthreads + `MAXIMUM_MEMORY` above 4 GB failed at link with `value 262144 is above the upper
bound 65536`, because the tooling still computed page counts against the 32-bit ceiling
(emscripten#26311, PR #26357). A link dying with that message means the SDK pin moved
backwards, not that the flag is wrong.

One long-standing claim in those sections is now measurably FALSE, and it is worth saying
plainly because it was used for a year to argue against a bigger heap: **growth does not
invalidate the GL patch table.** emsdk 6.0.9 no longer emits the `GROWABLE_HEAP_*()`
accessor form at all. Linking the same program with `ALLOW_MEMORY_GROWTH=1` produces the
growth machinery and *zero* accessors, on both wasm32 and wasm64
(`.github/workflows/wasm64-probe.yml`). The 841-rewritten-accesses problem was a 3.1.x
behaviour and it left with the SDK.

What does change at wasm64 is smaller than anyone expected: the heap is indexed by
division rather than shift (`>>2` becomes `/4`), because a pointer is a BigInt and BigInt
will not take `>>` with a Number. Of the 48 anchors in `tools/patch-freecad-js.py` only
**four** carry a heap index; the other 44 are byte-identical between targets. The tool
gained one relaxation and a selftest, not a rewrite.

The earlier reasoning is kept below for the record. Both sections are now historical.

### (historical, wasm32) Memory: the heap grows to 4 GB

**Status 2026-09-02:** the shipped link is `-sINITIAL_MEMORY=1073741824
-sMAXIMUM_MEMORY=4294967296 -sALLOW_MEMORY_GROWTH=1` (see
`scratchpad/linkcmds/fc-linkcmd-weh.sh`); the live `FreeCAD.js` constructs
`WebAssembly.Memory({initial: 1 GB, maximum: 65536 pages})`, i.e. a 4 GB ceiling. The
patch table in `tools/patch-freecad-js.py` was re-derived for the `GROWABLE_HEAP_*()`
accessor form, which is what the section below said had to happen first.

One consequence that bit: the page's memory-pressure monitor divided by
`HEAPU8.buffer.byteLength`, which on a growable heap is the *current* size (1 GB at
boot), not the ceiling -- so it warned "nearly full, cannot grow past 2 GB" at ~800 MB
used and force-saved before the first grow. It now divides by `maxByteLength`. Anything
else that treats `byteLength` as the ceiling has the same bug.

The original reasoning is kept for the record:

### (historical) Memory: the heap is a fixed 2 GB, deliberately

`-sINITIAL_MEMORY=2147483648 -sALLOW_MEMORY_GROWTH=0`. Growth was built and measured
(`scratchpad/linkcmds/fc-linkcmd-weh-grow.sh`, since removed with the wasm32 lane;
initial 1 GB / maximum 4 GB) and **not
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
