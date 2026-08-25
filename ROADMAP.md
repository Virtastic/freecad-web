# Roadmap: from "works" to "someone can do their job in it"

> **Status 2026-08-18.** Four things changed today and two of them were defects nobody knew
> about, so read this table before the prose below it -- the prose is older.
>
> | # | item | state |
> |---|---|---|
> | 9 | **Edge caching** | **fixed and live.** `FreeCAD.wasm` and `FreeCAD.data` returned `cf-cache-status: DYNAMIC` -- Cloudflare judged them ineligible and went to the origin every time, so every cold visitor pulled ~119 MB off the single OVH VPS. The rule `infra/terraform` declares had never been applied. Applied via `.github/workflows/cache-rules.yml` (run 32209996790); all three assets now HIT. |
> | 10 | **CalculiX stubs** | **19 -> 3**, 974/975 routines translate, and the module is within **1,079 bytes** of production (was 986,945). Of the three left, `e_c3d_us45` is stubbed in production too, and the two mortar-contact routines are refused on purpose. See `docs-ccx-stubbed-routines.md`. |
> | 11 | **Clean-checkout build** | **still blocked, but by one command.** `gl_compat.h` and `qprocess_stub.h` are force-included into everything and exist only on the build machine. `bash tools/capture-build-machine-headers.sh` there, and commit. |
> | 12 | **CI trustworthiness** | Coin3D had never been built at all; `patches/apply.sh` had never applied a patch in CI; OCCT was compiling with two exception models at once; CPython lost JSPI entirely without `-DPY_CALL_TRAMPOLINE=1`. All fixed, all gated. Eight of 23 dependencies now build on a hosted runner. |
>
> **Status 2026-08-19: what "fully usable" still needs.** Asked directly whether the app has
> network access and plugins. Checked rather than assumed, and the answer is *partly*, with
> four gaps that are now tracked items rather than surprises.
>
> | # | item | state |
> |---|---|---|
> | 13 | **Outbound HTTP** | **works in principle, constrained in practice.** QtNetwork is part of qtbase and IS built (`-submodules qtbase,qtsvg,qtdeclarative,qttools`), and Qt-for-wasm implements `QNetworkAccessManager` over the browser's fetch. `DownloadItem`/`DownloadManager` use it. BUT `infra/nginx.conf` sets `Cross-Origin-Embedder-Policy: require-corp`, which SharedArrayBuffer (and therefore threads) requires -- and under it every cross-origin response must carry CORP/CORS headers or the browser refuses it. Most third-party hosts do not. So requests to arbitrary sites will mostly fail, and anything that needs to reach the wider web needs a same-origin proxy. Not yet built. |
> | 14 | **What the QProcess stub disables** | **audited 2026-08-20; the original entry here was wrong.** It said `NetworkRetriever` was FreeCAD's "fetch from the web" helper and that "anything routed through it silently does nothing". Read against the 1.1.3 tree, **nothing is routed through it**: it is referenced by its own two files, `src/Gui/CMakeLists.txt` and the translation catalogues, and by no other code. The live download path is `DownloadManager`/`DownloadItem` on `QNetworkAccessManager`, which works. The real inventory is `docs-qprocess-stubbed-features.md`: of 24 files mentioning QProcess, 2 use only `QProcessEnvironment` (a separate Qt feature, still enabled -- these work), 6 are include-only, 2 are dead upstream, 4 fail honestly because they check a return value, 3 are self-restart which a page cannot do, and **exactly 2 fail silently** -- gmsh remeshing (`RemeshGmsh.cpp`) and run-external (`DlgRunExternal.cpp`). gmsh is already a wanted archive, so that one turns into a feature rather than a repair. |
> | 15 | **Addon Manager / plugins** | **off entirely.** `BUILD_ADDONMGR=OFF`, because AddonManager is a git *submodule* and GitHub tarballs carry none. Beyond fetching it, installing an addon at runtime assumes `git` and a writable install tree, both via QProcess -- so it needs a wasm-native install path (fetch a zip over HTTP, unpack into IDBFS) before it means anything. This is the single biggest gap against "usable by anyone". |
> | 16 | **Compiled Python addons** | **not possible by construction, and that is worth stating.** This is one static monolith: every C extension is registered in `MainGui.cpp`'s inittab at link time. There is no `pip`, no dynamic loading. Pure-Python addons can be dropped into the virtual filesystem and will work; an addon shipping a compiled extension cannot be installed without relinking the whole binary. |
> | 17 | **Web workbench** | **re-measured 2026-08-24 and largely a non-issue.** Mod/Web in 1.1.3 is a *server* (App/Server.cpp), not a browser view -- there is no QWebEngineView in the module at all, so "qtwebengine is skipped" costs it nothing. What users actually press are the nine QDesktopServices::openUrl sites in Gui (help, wiki, macro links, project info), and those work in the browser build: openUrl returns true and calls window.open with the URL. Now gated by tools/boot-gate.py --scenario network. |

> | 18 | **PySide/shiboken lane** | **the last archive lane, and the one written most tightly to one machine.** `rebuild-pyside-weh.sh` passes `-DQT_HOST_PATH=$ROOT/qt/6.9.0/macos` (macOS-only), `-DPython_EXECUTABLE=.../build/python.exe` (macOS-only name), `-DQFP_PYTHON_HOST_PATH=/usr/bin/python3` (hardcoded), and needs `deps/host/shiboken6` -- a HOST shiboken built against libclang, which nothing in CI produces. Every one of these is the same defect the numpy/pivy/IfcOpenShell lanes each hit; they are just all in one script. Needed for `deps/wasm/pyside-pkg`, which the link preloads. |
>
> **Item 18 update, 2026-08-20. The blocker is found and fixed; the lane is now finishing.**
> Eleven archives were already green and verified by symbol -- numpy (4), matplotlib (13),
> kiwisolver, `_ctypes`, libffi, PIL, pivy `_coin`, IfcOpenShell `_ifcopenshell_wrapper`
> (358/358 targets) -- alongside a clean 2676/2676 C++ compile across 29 modules. PySide was
> the twelfth and the only one still failing.
>
> **The cause.** shiboken injects a clang builtins directory ahead of *everything the
> compiler reports*, from `appendClangBuiltinIncludes()` in
> `ApiExtractor/clangparser/compilersupport.cpp`. Its `<stddef.h>` is then found before
> libc++'s own, and libc++ refuses -- `<cstddef> ... didn't find libc++'s <stddef.h>` -- so
> `nullptr_t` is undefined in all 126 errors downstream. em++ already orders its own search
> correctly (libc++, sysroot, builtins LAST), so the injection was the whole problem.
>
> Six command-line approaches were tried first and all six were *structurally* incapable of
> fixing it, because shiboken assembles its own arguments before the `--clang-option` ones
> are appended. Counted identically -- an earlier version of this entry compared two runs
> with different grep patterns and reported false progress -- every one produced the same
> 126 errors: libclang 17/19/20, `-resource-dir`, `-nobuiltininc`, `-std=c++17`,
> `--include-paths=<libc++>` (passed first, searched *eighth*: clang drops a normal include
> dir that duplicates a system dir and keeps the system position), and `-isystem<libc++>`.
> `tools/patch-shiboken-builtin-includes.py` changes the injection where it is made instead.
> One `clang -v` run settled in minutes what six blind CI rounds could not.
>
> **The generator now works**: 5 invocations, 0 parse errors, all three modules generated
> (`Ran Source generator` / `Ran Header generator` for each). Two consequential failures
> followed, both expected once the shape was understood:
>
> | failure | cause | fix |
> |---|---|---|
> | `pysidetest` -- `/usr/include/c++/15/cstddef: 'stddef.h' file not found` | that module parses **host** headers, which genuinely need the injection this build removes | `-DBUILD_TESTS=OFF` -- the same reason shiboken's own `samplebinding` is off, and only Core/Gui/Widgets are wanted |
> | AUTOMOC: `qprocess_unixprocessparameters_wrapper.cpp does not exist` | `check_os()` reads `CMAKE_HOST_WIN32`, so a Linux-to-wasm cross build takes the Unix branch and asks QtCore for a class Qt-for-wasm has not got | `tools/patch-pyside-drop-absent-classes.py`, following the file's own `permissions`/`sharedmemory` idiom |
>
> `QProcess` and `QProcessEnvironment` survive that second one only because their typesystem
> entries carry `<configuration condition="QT_CONFIG(process)"/>` and still get a guarded,
> empty wrapper; the nested `UnixProcessParameters` value-type has no such condition, so
> nothing is written at all. It is the same absence as items 14 and 15 above -- no
> subprocesses in a browser -- surfacing in a third place.
>
> Two related defects were fixed alongside: nothing ever created `deps/wasm/pyside-pkg`, so
> `patches/apply.sh` (which populates it only `if [ -d ]`) had never copied the glue and the
> preload would have been empty; and the lane's "already built" check keyed on that same
> directory of hand-written Python, which proved nothing about the build. Both now key on
> `QtWidgets.abi3.a`, and the gate checks all five archives the link names.
>
> **The last defect was emstrip.** With everything above fixed the build completed in full --
> `[694/694] Linking CXX static library PySide6/QtWidgets/QtWidgets.abi3.a` -- and every
> module archive still came back from `llvm-nm` as
>
> ```
> QtCore.abi3.a:qabstractanimation_wrapper.cpp.o: no symbols
> ```
>
> with no `PyInit_QtCore` anywhere, while shibokenmodule's object file showed a clean
> `00000001 T PyInit_Shiboken`. `create_pyside_module()` ends with `qfp_strip_library()`,
> which adds a POST_BUILD `${CMAKE_STRIP} $<TARGET_FILE:...>` under
> `CMAKE_STRIP AND UNIX AND NOT APPLE AND NOT QFP_NO_STRIP AND NOT Debug`
> (`ShibokenHelpers.cmake:89`). `CMAKE_STRIP` here is **emstrip**, which drops the symbol
> table outright. shibokenmodule survived because it is not a `create_pyside_module` target.
>
> Note the guard: **`NOT APPLE`**. The port was authored on a macOS build machine where that
> branch never fires. This is the third host-shaped decision inside a cross build found in
> two days -- after `check_os()` reading `CMAKE_HOST_WIN32`, and `pysidetest` parsing host
> headers -- and `BUILD-WEH.md` had carried the warning "emstrip drops the symbol table" the
> whole time without anything applying it to this lane. Fixed with `QFP_NO_STRIP=ON` and
> `CMAKE_STRIP=/usr/bin/true` on both configures.
>
> Two further things this uncovered, both fixed: `append_size_optimization_flags()` was
> compiling every binding module `-fno-exceptions` while the rest of the port is
> `-fwasm-exceptions` (mixing exception models in one link is ROADMAP 12's OCCT defect
> again) -- disabled via `QFP_NO_OVERRIDE_OPTIMIZATION_FLAGS`; and `patches/apply.sh` aborted
> the whole job on a restored source cache, because `tools/patch-pyside-clang-options.py`
> edits *inside* the branch `pyside-setup.patch` adds, so neither the forward nor the reverse
> dry-run matches. `apply_one()` now takes an optional `<file>::<string>` marker for patches
> that later tooling makes irreversible.

> **Item 18 CLOSED, 2026-08-20.** All twelve archive lanes are green and the gate passes in
> full: numpy (4), matplotlib (13), kiwisolver, `_ctypes`, libffi, PIL, pivy `_coin`,
> IfcOpenShell, and **PySide6 QtCore / QtGui / QtWidgets + libpyside6 + libshiboken6**, each
> verified by symbol rather than by filename --
>
> ```
> build-pyside-wasm/PySide6/QtCore/QtCore.abi3.a:       000014f8 T PyInit_QtCore
> build-pyside-wasm/PySide6/QtGui/QtGui.abi3.a:         00002579 T PyInit_QtGui
> build-pyside-wasm/PySide6/QtWidgets/QtWidgets.abi3.a: 0000071a T PyInit_QtWidgets
> ```
>
> One more defect surfaced immediately after, and it is worth recording because it made a
> FIXED build look broken: the pydeps cache key hashed five configure scripts and
> `numpy.patch`, none of which the PySide work touched. So the key was byte-identical to an
> entry saved before the fix, `actions/cache` refused to overwrite it --
> *"Failed to save: Unable to reserve cache with key ..."* -- and the very next job restored
> the STRIPPED archives and failed the PyInit check on a defect that had already been fixed
> and verified in the run before it. The key now hashes every lane recipe.
>
> **Item 20, new 2026-08-20: the link now runs in CI.** `link-freecad.yml` runs the
> production path end to end -- `build-weh-objs.sh`, `configure-gui-weh.sh`, `ninja`,
> `ninja install`, `fc-linkcmd-weh.sh`, GL post-patches, `WebAssembly.validate` -- and
> uploads `FreeCAD.js` / `FreeCAD.wasm` / `FreeCAD.data`. Nothing in this repository had ever
> produced those anywhere except one machine. Four build-machine assumptions had to go first:
>
> | what | why it only worked there |
> |---|---|
> | `configure-gui-weh.sh` | named `python.exe`, `qt/6.9.0/macos`, and a pybind11 under `python3.14` |
> | `weh-objs/*.o` | eight objects cmake does not build, existing only as `em++` lines in comments -- now `build-weh-objs.sh`, each verified by symbol |
> | `fc-linkcmd-weh.sh` preload | named `build-freecad-gui`, the NON-weh build directory, which only `configure-gui.sh` produces |
> | `fc-linkcmd-weh.sh` archives | named `build-pivy-wasm/` and `build-ifcopenshell/` build trees; the staged `deps/wasm/lib/{pivy-mod,ifc-mod}` copies are what is gated and cached |
>
> > **Item 20 CLOSED, 2026-08-21. The browser build runs end to end in CI.**
>
> ```
> Which objects were built with the wrong exception model?
>   scanned 3891 object(s)/archive(s); 0 reference JS-EH
> Compile   reached: [2701/2701]   failed targets: 0
> Install   Mod: 29 workbench dirs   Ext: 23 files   share: 1169 files
> Link      (no errors)
>           bin/FreeCAD.data   144,971,188
>           bin/FreeCAD.js         845,051
>           bin/FreeCAD.wasm   157,006,860
> GL        patched build-freecad-gui-weh/bin/FreeCAD.js   (33 patches + 7 counters, --check clean)
>           FreeCAD.wasm VALID, 149.7 MB
> ```
>
> `link-freecad.yml` is green. Every defect between the first attempt and this was the same
> shape -- something that only worked on the machine that had run it before:
>
> | defect | why it only worked there |
> |---|---|
> | `configure-gui-weh.sh` truncated at `-Dpybind11_DIR` | two bare `#` comments inside a `\`-continuation ended the command; the build dir already held the rest in `CMakeCache.txt` |
> | `weh-objs/*.o` | eight objects cmake does not build, existing only as `em++` lines in comments |
> | `find_package(Threads)` | its try_compile LINKS, and `CMAKE_EXE_LINKER_FLAGS` named `DraftUtils.a`, which does not exist until the build produces it |
> | freetype headers | pointed at a matplotlib *source* subproject nothing cached |
> | thin archives | meson emits `libagg.a`/`libfreetype.a` as references, not code; copying the `.a` staged something that looks like a library and is not |
> | numpy staged 19 of 40 archives | only the `*.so.p` extension modules were harvested, never npymath/mtargets/highway |
> | exception model | the meson cross-file said `-fexceptions` while everything else is `-fwasm-exceptions`; found by scanning 3891 objects, not by guessing |
> | ICU single-threaded | `embuilder build icu` uses DEFAULT settings; and our own `FindICU.cmake` did not know about emscripten's `-mt` suffix |
> | Qt's bundled zlib | Qt is built with `Z_PREFIX`, so `libQt6BundledLibpng.a` wants `z_inflateReset2`, which `--use-port=zlib` cannot provide |
> | ICU absent from the link line | the recorded command predates FreeCAD 1.1 adding ICU |
> | **the browser link failing silently** | the recorded command ended `&& :`, discarding wasm-ld's exit code. Three runs reported "success Link" with 21 errors each |
>
> Two stale-cache traps were closed for good along the way: staging scripts now write a
> `.staged` version marker that the lanes require, and `actions/cache`'s path list is kept
> byte-identical between the producing and consuming workflows -- the cache VERSION is
> derived from that list, so a drifted copy silently restores an older entry and reports
> success.
>
> **Not yet verified: that it BOOTS.** The wasm validates and every archive is present and
> symbol-checked, which is not the same as running. That is the next thing.
>
> **Item 19, new 2026-08-20: `BUILD_FLAT_MESH` is off and nothing recorded it.** Audited
> every one of FreeCAD 1.1.3's 45 `BUILD_*` options against `configure-gui-weh.sh`. Every
> module upstream defaults ON is ON here except three, and only one of those is a real gap:
>
> | option | upstream | ours | verdict |
> |---|---|---|---|
> | `BUILD_ADDONMGR` | ON | OFF | known -- ROADMAP 15 |
> | `BUILD_DYNAMIC_LINK_PYTHON` | ON | OFF | correct: this is one static monolith |
> | `BUILD_FEM_NETGEN` | ON *(MSVC only)* | unset | correct -- the non-MSVC default is OFF, so unset matches every Linux/macOS build |
> | **`BUILD_FLAT_MESH`** | **ON** | **OFF** | **a real missing feature** |
>
> `flatmesh` is MeshPart's surface unwrapper (`FaceUnwrapper`, LSCM relaxation -- flattening
> a curved face into a 2D pattern). It needs Eigen >= 3.4.0 and pybind11, both of which this
> build already has, so nothing forced it off. `src/Mod/Mesh/InitGui.py:47` does
> `try: import flatmesh ... except ImportError: PrintLog`, so the Mesh workbench still loads
> and the flattening commands are simply **absent, silently, to the log only**.
>
> Enabling it is three changes, not one: `BUILD_FLAT_MESH=ON`; `flatmesh.a` on the link line;
> and a `PyImport_AppendInittab("flatmesh", PyInit_flatmesh)` in `MainGui.cpp`, since
> `MeshPart/App/CMakeLists.txt` builds it as a SHARED library and `force-static.cmake`
> turns it into an archive that nothing would otherwise pull in. The inittab currently holds
> 70 entries and this is not one of them. Deferred until the first link succeeds, so an
> untested module is not added to a link that has never run.

> **Status 2026-08-16** (the original table; items 1-8 below are unchanged unless noted).
>
> | # | item | state |
> |---|---|---|
> | 1 | QInputDialog | **shipped** — natives restored, live, harness written |
> | 2 | Error reporting | **shipped** — four anonymous counters, live and recording |
> | 3 | Storage evictable | **shipped** — user-nominated backup folder, live |
> | 4 | GL no-op inventory | **done, and acted on** — 49 empty entry points down to 34. `glMaterialf` was discarding `GL_SHININESS`; eight immediate-mode doubles were discarding geometry outright. `tools/gl-noop-inventory.py` tracks the rest and ci.yml compiles the shims. |
> | 5 | Display lists / 11 fps | **scoped** — C change + relink + pixel gate, not a JS patch |
> | 6 | 2 GB heap | **implemented, opt-in** — `FCWEB_HEAP_BYTES`; needs a link + `heapprobe.js` |
> | 7 | CalculiX threading | **reproducibility closed; threading still unshipped** — see below |
> | 8 | Chrome/Edge only | **decided** — track, don't build |
>
> **Item 7, corrected 2026-08-18. The reproducibility verdict below has been superseded, and
> this entry said the opposite of the truth for two days.** It read "production's ccx.wasm is
> not reproducible" and "the ccx.wasm currently in production cannot be reproduced from this
> repository plus upstream sources". That was accurate when written (run 31996275820's
> predecessors) and is no longer: `docs-ccx-stubbed-routines.md` is the authority and records
> the work that closed it.
>
> | | then | now |
> |---|---|---|
> | stubbed routines | 69 | **19** |
> | translated | 908/977 | **959/977** |
> | gap to production's code section | 986,945 B | **97,074 B** |
> | validation decks vs production | differ | **identical, digit for digit** |
>
> All four decks (elastic, frequency, plastic, thermal) reproduce production's numbers
> exactly, including the 1e-13 round-off noise — which is what makes it a reproduction rather
> than a resemblance, since round-off is where two differently-built solvers diverge first.
> The gate has been blocking since run 31992713435 and the workflow is green (run 32013729412).
> So a clean build from this repository plus upstream sources now produces a CalculiX that
> behaves like the one in production, with no undocumented edits on a build machine.
>
> **What is genuinely still open, and it is not the schedule:**
>
> - **Mortar contact is deliberately stubbed** (`SKIP_FILES` in `tools/f77ify.py`). Bounding
>   `slavintmortar`/`slavintpoints` produced a converged but *physically invalid* answer —
>   negative contact pressure, asymmetric response to a symmetric model — where production is
>   correct. A stub aborts by name; a bounded routine returns a wrong number, and for a solver
>   the second is far worse. Carried as a KNOWN GAP because mortar contact was 100% stubbed in
>   a clean build, so there is no working state to have regressed from.
> - **Threading is still unshipped.** `FCWEB_CCX_PTHREADS=1 bash build-ccx-weh.sh` builds
>   clean, but the decks must **match** today's numbers rather than merely converge — a race in
>   the assembly is a slightly different answer, not a crash. The threaded artifact is attached
>   to the run as `ccx-wasm-pthreads`.
>
> The lesson worth keeping is the one about status blocks: this table asserted a blocker that
> the work had already removed, and nothing in the repository noticed. Check the gate, not the
> summary.
>
> **Item 6 is still one command, and still needs the build machine.** Both are implemented and
> parameterised, and both default to exactly today's behaviour so nothing changes until
> someone opts in:
>
> ```bash
> FCWEB_HEAP_BYTES=3221225472 bash configure-gui-weh.sh   # 3 GB heap
> FCWEB_CCX_PTHREADS=1        bash build-ccx-weh.sh       # threaded CalculiX
> ```
>
> What still needs the build machine is the *link and the verification*, which CI genuinely
> cannot do — it only downloads release assets, it never compiles. Neither should be believed
> because it built: `scratchpad/heapprobe.js` exists because the heap hazard shows up as a
> wrong number rather than a crash, and the CalculiX decks must **match** today's results
> rather than merely converge. Do the heap one alone, in its own link.
>
> **Item 5, scoped properly — and my earlier guess about it was wrong.** I said display lists
> were "plausibly a new patch at untouched sites", i.e. shippable without a relink. Checked,
> and they are not. The display-list entry points are **entirely absent from the JS glue** —
> not stubbed, absent — because they are stubbed in C, in `gl_legacy_stubs.c`, which is linked
> into the binary:
>
> ```c
> GLuint glGenLists(GLsizei range) { return 0; }  /* 0 => no display lists => immediate mode */
> void glNewList(GLuint, GLenum) {}   void glEndList(void) {}
> void glCallList(GLuint) {}          void glDeleteLists(GLuint, GLsizei) {}
> ```
>
> So this is lane C: a C change, a relink, and real work — a display list means recording and
> replaying a GL command stream, not filling in a function. The stub is also deliberate, and
> its comment explains the trade: returning 0 makes Coin fall back to immediate mode, which
> the emulation *does* support.
>
> It also needs pixel verification, which is not optional here: re-enabling render caching is
> the change that once made **nothing draw at all**. Canvas capture was tried and is unusable
> with a hidden browser pane — the page stops compositing and `toDataURL` returned a
> byte-identical frame across an empty scene, a solid, and a camera change. Use
> `scratchpad/shot.js` on a machine with a visible browser, behind a query flag.
>
> **Worth pricing the alternative first.** Coin can draw through VBOs instead of display
> lists, which is also lane C but avoids implementing a command recorder at all. Given the
> batching work already took the heavy scene from 10 to 21–34 fps, compare both before
> committing a day to either.
>
> **Two corrections worth keeping, both found by trying.** First, the deploy now runs
> `tools/patch-freecad-js.py` over the release asset, so patch-table changes are deployable at
> all — they previously had no route to production except a relink. Second, I claimed item 4
> then needed a relink anyway, because the release's `FreeCAD.js` is already patched and the
> `throw` sites are long gone. That was wrong: re-deriving each site from its surrounding
> context (`if(face!=1028&&face!=1032){0}`, `var _glTexGeni=(coord,pname,param)=>{0}`, …), with
> every anchor verified unique against the deployed file first, worked. Item 4 is done and the
> measurement is in BUILD-WEH.md.

Seven known gaps, planned. Written after a production verification pass on
`build-20260813-eventstack+c41d84b`, so the starting facts are measured rather than assumed.

**The single most useful thing to know first:** the cost of a change here is decided by which
lane it lives in, not by how hard it sounds.

| lane | cost | what's in it |
|---|---|---|
| **A — front-end** (`play-gui/*`) | minutes; deploy needs no relink | dialogs, storage, error reporting |
| **A2 — re-patch `FreeCAD.js`** via `tools/patch-freecad-js.py` | hours; still no relink | **the GL fixed-function gaps, and display lists** |
| **B — payload Python** (inside `FreeCAD.data`) | ~2 h relink | FreeCAD's own `.py` |
| **C — C++ / link line** | ~2 h relink | heap size, Coin, CalculiX threading |

Lane A2 is the surprise: the nine no-op'd GL calls and the stubbed display lists are patches to
emscripten's *generated JS glue*, already rewritten post-link by `tools/patch-freecad-js.py`.
Fixing them needs **no relink at all**. That moves the two rendering items from "expensive" to
"a day each", and it reorders this whole list.

---

## Tier 1 — blocks daily work, and costs almost nothing

### 1. `QInputDialog` always returns "cancelled" *(lane A, 0.5–3 d)*

> **Superseded 2026-08-24 — this is fixed and the prose below is history.** Re-measured
> against the running application: a real modal opens (visible, 240×107, one line edit)
> and returns the typed value — `getText` gave `('typed-by-test', True)`, `getInt` gave
> `(42, True)`. The status table at the top of this file already said "shipped"; this
> section did not, and it cost a re-investigation. `tools/boot-gate.py --scenario dialog`
> now holds the line.

Measured live today:

```
getText   -> ('', False)      getInt    -> (5, False)
getDouble -> (12.5, False)    getItem   -> ('a', False)
```

Every prompt-for-a-value dialog silently reports cancellation, so any macro or Python
workbench command that asks for a name, count or length quietly does nothing. Draft, BIM and
OpenSCAD tooling all rely on these.

**Do the cheap check first.** Commit `1c10855` measured *native* `QInputDialog` working under
JSPI and deleted the HTML bridge — yet the JSPI shim still stubs it. So either the shim is
stale dead weight, or that measurement didn't hold. Removing the four stub lines and testing
native behaviour is an hour, and might close the whole item.

If native genuinely doesn't work, build an HTML input modal on the **existing** blocking
pattern: `_fcwebdlg.confirm` already suspends under JSPI and returns the user's real choice
for `QMessageBox`. Same mechanism, one extra field.

**Prerequisite either way:** extract the JSPI shim to `play-gui/wasm_dialog_shim_jspi.py` with
a generator. It currently exists *only* as base64 inside `freecad-gui.html`, and its comment
points at the wrong source file. Nobody should hand-edit base64 to fix a dialog.

**Done when:** a macro calling `getText` receives what the user typed, and `getInt`/`getDouble`
round-trip a value, verified by real typing rather than through the Python bridge.

### 2. Documents can be evicted *(lane A, 3–4 d)*

`navigator.storage.persisted()` is **false** on a normal profile — confirmed again today.
Chrome only grants persistence to an installed app, so until someone installs the PWA the
browser may clear their work to reclaim disk.

The install prompt now fires after a first successful save (already shipped), but that is a
nudge, not a guarantee. The real fix is to stop depending on browser-managed storage at all:

**Let the user nominate a real folder.** `showDirectoryPicker()` returns a
`FileSystemDirectoryHandle` that can be persisted in IndexedDB and re-permissioned on later
visits. Autosave writes there as well as to IDBFS. Work then lives in an ordinary directory on
their machine — survives eviction, survives clearing site data, and is visible in their file
manager, which is what a CAD user expects anyway.

Steps: picker + handle persistence + permission re-request on boot; autosave writes both
places; a clear indicator of which mode is active; fall back silently to IDBFS-only where the
API is absent.

**Also verify the untested assumption:** that the Phase 2 engine cache survives PWA
installation rather than forcing a fresh 115 MB.

**Done when:** clearing site data does not lose a document that was open when it happened.

### 3. No error reporting *(lane A + a small endpoint, 2–3 d)*

Today a failure dies in the user's tab. `window.fcwebCrash` already builds a good report (120-line
ring buffer, heap, autosave list, UA) — it just has nowhere to go but the clipboard.

Two pieces, deliberately separate:

- **Anonymous counters** — boot started / boot succeeded / abort-by-kind / browser-gate
  rejection. No document names, no free text, no identifiers. This alone answers "what fraction
  of visitors never reach Ready?", which nothing currently can.
- **Opt-in detailed report** — the existing blob, sent only when the user presses the button,
  with **document names redacted first** (they're in there today, at `freecad-gui.html:614`).

Keep it first-party: a tiny endpoint on the existing nginx/Caddy writing JSONL, not a
third-party SDK. Cross-origin isolation constrains what can be embedded anyway, and this avoids
the privacy and CSP questions entirely.

**Done when:** a deliberately triggered abort appears server-side within a minute, carrying the
build id and no document names.

---

### 3b. shiboken still owns `PyObject_GetBuffer` / `PyBuffer_Release` *(lane A, 0.5 d)*

The same hazard that cost the 1.1.3 boot, one layer down. shiboken's limited-API
build defines its own `PyObject_GetBuffer` and `PyBuffer_Release`
(`bufferprocs_py37.cpp`), and in this static monolith those win the symbols for the
whole program — the wasm name section puts them at indices 742/743, in shiboken's
object cluster, not CPython's. `patches/pyside-setup.patch` renames the
`pep384impl.cpp` group out of the way but leaves this pair alone.

Unlike `PyMethod_New`, these do not depend on lazily initialised state, so they are
not obviously broken — shiboken's `Pep_buffer` is a re-declaration of `Py_buffer`
with `#define Py_buffer Pep_buffer`, so the ABI matches. The behavioural path does
differ (`PepType_AS_BUFFER` lookups rather than CPython's slot access), so **if a
boot or a memoryview/io path fails after the interpreter comes up, this is the first
suspect.** Treating it needs care: shiboken's own call sites are typed against
`Pep_buffer`, so removing the definitions outright will not compile. Renaming, as
the `pep384impl.cpp` group does, is the shape that works.

`tools/check-symbol-hijack.py` deliberately does not fail on these yet — a check
that fails on a known-unfixed condition is a check people learn to ignore. Add them
to its `RENAMED` list in the same change that renames them.

## Tier 2 — rendering, and much cheaper than it looks

### 4. Nine fixed-function GL calls silently do nothing *(lane A2, 1–2 d)*

`tools/patch-freecad-js.py` rewrites these from `throw` to `0`:

```
glLightModelf   glLightModelfv   glLightfv
glMaterialfv (×2)                glTexGenfv   glTexGeni
glTexCoord3f    glTexCoord4f
```

Turning a throw into a no-op was correct — a throw unwinds through Coin's render traversal and
takes the viewport with it. But **`glMaterialfv` and `glLightfv` are how Coin sets material
colour and lighting.** If they do nothing, shading and colour differ from desktop, and nobody
has ever inventoried by how much. That's a parity claim the project can't currently make.

1. **Inventory before implementing.** Add a counting wrapper (same mechanism as `?gltrace=1`)
   and drive the eight `workflows.js` scenarios plus each bundled example. Which of the nine
   are actually called, how often, and from which workbenches?
2. **Compare against desktop.** Same model, same camera, screenshot both. This is the only way
   to know whether "no-op" means "invisible" or "everything is the wrong colour".
3. **Implement what matters**, in the JS glue, as new entries in the patch table — material and
   light state feeding the emulation's existing uniform path. `glTexGen*` only matters if a
   workbench uses generated texture coordinates; the inventory says whether to bother.

**Done when:** every call site is either implemented or recorded, with a screenshot diff, as a
known and bounded divergence.

### 5. ~11 fps on heavy scenes; render caching forced off *(lane A2 spike → C, 3–8 d)*

> **Note on verifying this one.** Frame rate cannot be sampled from a hidden or headless-
> without-compositor page: `requestAnimationFrame` does not fire, so a probe just hangs
> rather than returning a low number. Confirmed 2026-08-17. Any measurement of this item
> needs a *visible* viewport — which is what `scratchpad/shot.js` and the pixel gate provide.
> Do not treat a timed-out probe as evidence of anything.

The cause is one line, and it is upstream of the symptom:

> `patches/freecad.patch:18060` — *"wasm: display lists are stubbed (glGenLists returns 0), so
> ON/AUTO render caching produces permanently-empty caches — children are never traversed after
> the first frame and nothing draws. Force caching OFF."*

So Coin re-traverses and re-emits the entire scene graph every frame, forever. The draw-call
batching already landed (10 → 21–34 fps); caching is the next order of magnitude, because it
skips the traversal rather than making it cheaper.

**Spike first, in lane A2 (~1 d):** implement display lists in the GL glue —
`glGenLists`/`glNewList`/`glEndList`/`glCallList` recording and replaying a command buffer. If
that works, `COIN_AUTO_CACHING` can go back on with **no relink and no C++ change**, and the
`patches/freecad.patch` hunk plus the two `pre-gui.js` env vars are simply reverted.

If recording proves impractical, fall back to Coin's VBO path (`SoVBO`), which is lane C and a
relink.

**Risk to respect:** caching was turned off because turning it on made *nothing draw*. Re-enable
behind a query flag first, verify with `scratchpad/shot.js`'s pixel gate before trusting fps
numbers, and measure load average before believing any timing — this repo has a documented
"50% regression" that was the machine's own build load.

**Done when:** BIMExample holds a materially higher fps with a pixel-identical render.

---

## Tier 3 — real limits, real cost

### 6. The 2 GB heap *(lane C, 2–5 d, genuine risk)*

**Measured on live production, 2026-08-17** (`build-20260813-eventstack+e835c2b`), via memory
reflection in the browser rather than from the build flags:

```
currentHeapMB : 2048      growthAllowed : false
```

So the shipped heap is exactly 2 GB and fixed, which confirms the flags below and means
`FCWEB_HEAP_BYTES`'s default (2147483648) is precisely what is already live. **There is
nothing to do to "reach" 2 GB — this item is only ever about going past it**, and everything
past it is the signed-pointer hazard, which needs the relink plus `scratchpad/heapprobe.js`.

Current: `-sINITIAL_MEMORY=2147483648 -sALLOW_MEMORY_GROWTH=0`. Measured ~72 KB per simple
solid → roughly 20,000 of them. Fine for parts; not for a large assembly.

`BUILD-WEH.md` rejected `ALLOW_MEMORY_GROWTH=1` for a good reason: it rewrites **841** heap
accesses into accessor form (`GROWABLE_HEAP_F32()[x>>>2>>>0]`), which invalidates the entire
hand-derived patch table, and the hot path *is* the JS GL emulation.

**That reasoning does not apply to simply asking for more.** With growth still off, emscripten
keeps direct `HEAPU8[...]` access, so **the patch table stays valid.** Raising `INITIAL_MEMORY`
toward 3–4 GB is therefore far cheaper than enabling growth.

The catch, and it is the whole risk: above 2 GB, pointers exceed `INT32_MAX`. Any C++ in OCCT,
Coin, Qt or CPython that stores a pointer in a signed `int`, or compares one, breaks — and
plausibly in a way that looks like corrupt geometry rather than a crash.

Sequence: measure what a real assembly actually needs → spike `INITIAL_MEMORY=3GB` with
`MAXIMUM_MEMORY` set → boot, run the full workflow suite, FEM end to end, and the pixel gate →
only then consider 4 GB. Keep 2 GB as the shipped fallback until a suite passes clean. Do **not**
pair this with other changes in the same link; if geometry goes strange you want one variable.

**Longer term:** wasm64 (`MEMORY64`) removes the ceiling properly, but it means rebuilding the
entire dependency stack for 64-bit pointers. Worth tracking, not worth starting.

### 7. CalculiX is single-threaded

> **Measured 2026-08-25, and the answer is: leave it alone.** A `-pthread` CalculiX was
> built (`build-ccx.yml -f pthreads=true`) and run against the serial one on the same
> decks, in the browser, through the real bridge:
>
> | deck | serial | threaded | threaded, 4 threads configured |
> |---|---|---|---|
> | 1 element | 0.5 s | 0.5 s | — |
> | 1,080 elements | 0.46 s | 0.45 s | — |
> | 8,640 elements | **2.80 s** | 3.09 s | **4.71 s** |
>
> Every run produced byte-identical output -- the same 2,008,434-byte `.frd` and the same
> maximum displacement of 0.0199569 mm -- so the threaded build is *correct*. It is simply
> not faster: unconfigured it pays for threading it never uses, and given four threads it
> is 68% slower than serial. Thread creation and atomics cost more in wasm than
> CalculiX's parallel sections save at these sizes.
>
> So this is not a limitation to fix. The serial build is the right configuration, and now
> there are numbers behind that rather than a note saying it was a stopgap.

Not an oversight — a deliberate stopgap that is honest about itself in `bridge/ccx_threads.c`:

> *"This module is not built with `-pthread`, so emscripten's `pthread_create` is a stub that
> fails — and ccx never checks the return value. The workers simply never ran: the matrix came
> out identically zero… ponytail: inline execution, revisit if a `-pthread` build is ever wanted
> for speed."*

The `__wrap_pthread_create` shim runs each worker inline, serialising what CalculiX intended to
parallelise. The main app already runs `-pthread` with `PTHREAD_POOL_SIZE=16` and the site is
cross-origin isolated, so `SharedArrayBuffer` is available — the ingredients are there.

Build `ccx.wasm` with `-pthread`, drop the `--wrap`, and let ccx's own `pthread_create` calls
run. Only the ccx module rebuilds; FreeCAD is untouched.

**Verify against the existing decks** (`scratchpad/ccxval/`: elas, freq, plast, therm) — results
must match the current numbers, not merely converge. Then measure speedup on the e2e box model;
if assembly parallelises but SPOOLES factorisation dominates, the win may be small, and that is
worth knowing before spending the time.

### 8. Chrome/Edge 137+ only *(not ours to fix)*

JSPI is the hard dependency, and it is what makes modal dialogs return real answers. Firefox has
it in development; Safari does not. The Asyncify fallback still exists in the tree but is the
known-broken variant — it cannot return a user's real choice and can corrupt the CPython stack.

**Plan: track, don't build.** The gate already refuses cleanly having downloaded nothing, which
is the right behaviour. Re-check Firefox each release; a second Asyncify build lane would double
the build matrix to ship a worse product.

---

## Suggested order

1. **QInputDialog** — cheapest fix to a thing that actively breaks work, and may be a deletion.
2. **Error reporting** — do it early; every later item is easier when failures reach you.
3. **Storage durability** — removes the one failure mode users cannot forgive.
4. **GL inventory** — cheap, and it either closes a parity claim or exposes a real one.
5. **Display-list spike** — highest performance upside per day spent, still no relink.
6. **Heap** — first change worth a relink; do it alone.
7. **CalculiX threads** — batch with the heap link if the decks pass.

Tiers 1 and 2 are all lane A/A2: **no relink, deployable the same day.** That is most of the
user-visible gap.

## A standing note

Two defects found on 2026-08-16 were invisible because every failure path was a swallowed
exception: autosave had never installed, and a debug gate had silently disabled autosave, the
out-of-memory warning and draw-call batching at once. Both looked completely normal.

So for every item here: **add a positive signal that the thing is alive**, not just an absence of
errors. "Nothing threw" has already proven itself worthless twice in this codebase.

## First-load size, measured 2026-08-24

What a first-time visitor actually pulls over the wire, from production, with brotli:

| asset | compressed |
|---|---|
| FreeCAD.wasm | 57.9 MB |
| FreeCAD.data | 30.2 MB |
| FreeCAD.js | 0.17 MB |
| **total** | **~88 MB** |

So the "~115 MB first load" quoted elsewhere is the uncompressed figure; the real cost is
~88 MB. And the `--profiling-funcs` name section, which looks like the obvious thing to
cut at 25.6 MB raw, is worth only **2.9 MB compressed** -- 3% of the download in exchange
for crash reports that can name a function. Keep it.
