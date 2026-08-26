<!-- SPDX-License-Identifier: LGPL-2.1-or-later -->
<!-- Copyright (c) Virtastic -->
# Release plan: from "it boots" to "we can put our name on it"

**Written 2026-08-24, against `build-20260824-freecad113` (commit `1ccbd1f`), which is live
on freecad.virtastic.app.**

FreeCAD 1.1.3 now starts in a browser and does real geometry: a `Part::Box` 10×20×30
recomputes to volume 6000.0 with 8 vertices and 6 faces under `App.Version()` 1.1.3. That
is the end of "does it run" and the beginning of this document.

The standard here is *no known issues at release*, so this plan is organised by what would
have to be untrue for that sentence to hold — not by what is easiest to do next.

---

---

## Progress, 2026-08-24 (later the same day)

| # | item | state |
|---|---|---|
| **R0** | boot gate | **done.** `tools/boot-gate.py` runs the artifact in headless Chromium and makes it build a `Part::Box`. Proven both ways: passes today's engine, and fails the pre-fix binary with the engine's own `err=failed to initialize importlib`. Wired into the link so no artifact ships unproven. |
| **R0b** | restore scenario | **done.** A second scenario keeps one browser profile across two loads and requires the document to come back with its geometry intact (volume 480.0, not merely a name in a list). Fails the pre-fix shell with "autosave never installed". |
| **R3** | shiboken buffer symbols | **fixed, awaiting the link that proves it.** Renamed in `patches/pyside-setup.patch`; PySide rebuilt green. `check-symbol-hijack.py` now watches all ten symbols and currently names the two that are still wrong in the shipped engine. |
| **R2** | `QEventLoop::exit` null function | **still open, and now understood to be elusive.** It does not reproduce in headless Chromium with 3D on or off, with the restore path working. Left open rather than closed; the detector sits in the gate's fatal list so a recurrence fails CI instead of being noticed by a person. |
| **R8** | `?no3d` disabled autosave | **found and fixed.** The compositor's early return sat in an IIFE that had grown to contain the memory monitor and the autosave install/restore poll, so the flag silently switched off durability. Users are on the default path, but `?no3d` is what someone with a GPU problem is told to use — and it is what the gate runs. |
| **R9** | patched trees trusted a stamp | **found and fixed.** A run reported "already applied (marker + hash)" for a tree that lacked the lines the patch adds. `tools/verify-patch-applied.py` now checks the content, and both `apply.sh` and the workflow require stamp and content to agree. Second time this shape of bug has cost this project a build; the first cost it the boot. |

| **R4** | `QInputDialog` cancels everything | **closed by measurement, not by work.** The ROADMAP entry was stale: the stub is gone, the modal opens, and the typed value comes back. Now a gate scenario so it cannot rot again. |

| **R5** | documents can be evicted | **built and wired; one human check left.** Manifest and service worker meet the installability bar, the install offer waits until real work is saved, and a refusal warns the user and offers a disk backup folder. The grant itself cannot be tested headlessly, so it moved to MANUAL-QA. |

| **R6** | failures invisible from the field | **closed.** Script errors and unhandled rejections were shown to one user and counted for nobody; both now beacon an enumerated class. Still no message, stack or identifier — the detail stays on the user's clipboard. |

| **R10** | half of every third-party Python package missing | **found today, fix landed, awaiting a build.** numpy, matplotlib, PIL, ifcopenshell and pivy cannot be imported in the live release: C halves linked, Python halves absent. FEM, Draft, BIM and Plot are dead. Staging is now repo-driven and the gate imports them in a real browser. |

| **2.1** | outbound HTTP blocked by COEP | **built, tested, deployed.** A same-origin proxy with fixed destination keys (no `?url=`, so no SSRF into the box's own network), reads only, no credentials forwarded, rate limited. Verified against the real hosts: GitHub metadata, a 1.4 GB codeload stream, 403 for an unknown key and for POST. |
| **2.2** | Addon Manager off | **build half done.** The submodule is fetched at the commit 1.1.3 pins and `BUILD_ADDONMGR=ON`; its network is routed through the proxy at NetworkManager's single request chokepoint. Runtime install still to verify. |
| **2.2b** | PySide6 had no QtNetwork, then no QtSvg | **all five wiring points verified for both.** The Addon Manager's PySideWrapper imports QtCore, QtGui, QtNetwork, QtSvg and QtWidgets in ONE statement and reports the same "No viable version of PySide" whichever is missing. Each module needs five things and QtSvg now has all five, each checked rather than assumed: built (`-DMODULES` from `PYSIDE_MODULES`), carries `PyInit_QtSvg` (CI: "every archive in Core;Gui;Widgets;Network;Svg carries its PyInit"), on the link command CI actually runs, registered in the inittab, aliased in the package glue. `tools/check-pyside-link-line.py` cross-checks all of it and reads BOTH link lines, having been fooled once by reading only the one people read. |
| **2.5** | gmsh remeshing failed silently | **fixed.** It now calls the same wasm gmsh bridge the FEM mesher uses, and says so on the console when gmsh returns non-zero instead of leaving the mesh quietly unchanged. |
| **2.6** | Web workbench "has no engine" | **overstated; measured.** Mod/Web in 1.1.3 is a server, not a browser view. The nine `QDesktopServices::openUrl` sites in Gui do work -- openUrl returns true and calls `window.open`. Gated. |
| **2.10a** | first-load size | **brotli added** beside the existing gzip copy of FreeCAD.data, preferred when the client offers it, gzip untouched for anything older. |

| **R1** | FEM never ran end to end | **closed, with a number.** A 100x20x20 steel bar meshed by gmsh and solved by CalculiX entirely in the page comes out at **0.989** of the closed-form answer -- 113 nodes, 275 volumes, 100 N in the deck, 0.000118 mm against F*L/(E*A) = 0.000119 mm. It took five separate fixes to get there, all of the same shape: code that was present and could not run (see section 0b). The gate's `fem` scenario runs exactly this and fails on the ratio, not on an exception. |

| **R11** | the shipped FEM example crashes the engine | **fixed, and proven at the link level from the binaries themselves.** `tools/wasm-archive-sig.py` reads the signature of a symbol on both sides of a static-library boundary. In the engine that crashed: `vtkXMLParser::GetXMLByteIndex()` is defined at function index **136413** -- the exact frame in the crash stack -- while `vtkexpat_XML_GetCurrentByteIndex` is **absent from the name section**, i.e. the provider was dropped and the call became a trapping stub. In the rebuilt libraries the provider (`xmlparse.c.o`) and the consumer (`vtkXMLParser.cxx.o`) both read `(i32) -> i32`, for ByteIndex, LineNumber and ColumnNumber alike, so there is nothing left for wasm-ld to reconcile. The gate's `examples` scenario is now confirmation rather than discovery. |

| **V1** | upgrade path never tested | **now tested, and it passes.** The gate's `upgrade` scenario boots the PREVIOUS engine, saves work, deploys the new one over it -- md5-stamped URLs and all, exactly as infra/Dockerfile does -- and reloads the same profile. Measured: 182,656,749 bytes of engine replaced by 183,464,581, and the document written by the old build comes back in the new one with its geometry (volume 480.0). Getting there found a real fault: the shell's `fcweb-engine` Cache Storage is keyed on the URL alone, so an UNSTAMPED deploy hands the new loader the previous build's data package and the app dies with "Failed to import encodings module" -- reproduced 3 times in 4. The Dockerfile refuses to ship unstamped, so production is safe by construction; the shell now also validates the cached package against the size the engine asks for and empties the cache when they disagree, so a stamping slip costs one reload instead of a permanently broken app. |

| **V7** | every link costs ~90 minutes | **understood, deliberately not changed.** The link keeps `deps/src/freecad` pristine and re-applies freecad.patch every run, so ~200 files get a new mtime and ninja rebuilds 1,860 of ~2,700 edges -- about 75 of the 90 minutes. Caching the PATCHED tree would fix it and is exactly the shape that once cost this project its boot (a stamp said "patched", the tree was not). Two cheaper wins are already in: the compat headers are no longer rewritten when identical, and a failed link can no longer pass a stale binary downstream. |

| **2.2c** | the Addon Manager's catalogue fetch may block | **watch item, not yet a finding.** With a placeholder standing in for the missing QtSvg, the workbench's own PySideWrapper imports and then `NetworkManager.InitializeNetworkManager()` + `blocking_get()` does not return inside 90 s. Inconclusive -- it may be the placeholder rather than the real path -- but the gate's `addons` scenario drives exactly those two calls with a 120 s wait, so a real hang there fails the gate rather than shipping. Worth reading first if `addons` times out on the next run. |

R7 is untouched.

---

## 0. The gap that let a dead build look healthy for the whole port

Everything below matters less than this one item.

For the entire 1.1.3 port, the application **could not start at all** — and every gate we
had was green. CI compiled, linked, validated the wasm, checked the GL patch table, checked
the exception model, checked archive symbol counts, and deployed. Not one of them ran the
program. The bug was found only because a person opened the page.

Worse, the fix for it had already been written in an earlier session and was gated on
`FCWEB_REAL_CPYTHON`, a macro **defined nowhere in this repository**. It had been silently
inert for months. A guard that can go quiet is not a guard.

## 0b. Code that is present and cannot run

The FEM work turned up eight instances of one failure, and they are worth listing together
because the shape is the point: each one compiles, each one reads like a fix in review, and
each one never executes.

| where | how it could not run |
|---|---|
| the boot fix | `#ifdef FCWEB_REAL_CPYTHON`, defined nowhere |
| `apply.sh` | a marker that matched any version, so a stale tree passed as patched |
| the FEM symbol dir | a guard keyed on `.empty()` when the value was wrong but not empty |
| the gmsh bridge | appended to `update_properties()`, which runs *after* the mesh is read |
| `get_gmsh_command` | spliced into the middle of an `if` body, leaving the rest after a `return` |
| `_FcwebGmshProcess.waitForFinished` | shadowed by an older stub further down the class returning `True` |
| `setup_ccx`'s wasm branch | pasted **inside the docstring**: valid Python, and prose |
| `vtk-expat-wasm-xmlsize.patch` | written, committed, named in a cache key, applied by nothing |

Three of them reported success while doing nothing, which is worse than failing.

The response is not more careful reading. It is four checks that run in about a second
each: `tools/check-unreachable-fcweb.py` (unreachable, shadowed, stringified),
`tools/check-every-patch-is-applied.py`, `tools/check-pyside-link-line.py`, and
`tools/verify-patch-applied.py`. Each was written after the bug it catches, and each
reports that bug on the commit before its fix and is silent on the commit after.

### R0. A boot gate that actually runs the application *(blocker, ~1 day)*

Add a CI job that launches headless Chrome against the built artifact and asserts:

1. the page reaches `Ready` (the overlay reports it, `window.__fcAppReady` is set),
2. no `Fatal Python error`, no `Aborted()`, no `RuntimeError` on the console,
3. a scripted `Part::Box` recomputes to the expected volume and topology,
4. `App.Version()` matches the release being built,
5. the run finishes inside a fixed time budget (a hang is a failure, not a wait).

This is the same check performed by hand today; the whole point is that a machine performs
it on every link. Requires cross-origin isolation headers, so serve the artifact from a
local static server with COOP/COEP in the job (`build-artifact-serve/server.py` already does
exactly this).

**Done when** deliberately reverting the shiboken rename makes this job fail.

---

## 1. Release blockers

### R10. Half of every third-party Python package is missing *(blocker, and it is live)*

**Production right now cannot `import numpy`.** Nor matplotlib, PIL, ifcopenshell, or
pivy. Their C extensions are linked into the binary and registered in CPython's inittab —
`numpy._core._multiarray_umath` really is a builtin module in the shipped wasm — but the
Python packages they belong to are not on the virtual filesystem, so nothing can reach
them. Measured in the running application:

```
numpy ModuleNotFoundError · matplotlib ModuleNotFoundError · PIL ModuleNotFoundError
ifcopenshell ModuleNotFoundError · pivy.coin ImportError · Draft ImportError
femmesh.gmshtools ModuleNotFoundError
```

That is **FEM, Draft, BIM and Plot dead**, plus any macro that imports numpy.

The cause is the fragility ROADMAP #11 warned about, realised. `/pyside-pkg` held 1,850
files in the 2026-08-13 release — numpy, matplotlib, ifcopenshell, fontTools, PIL, lark,
dateutil and the rest — and holds **three** today: the PySide6, shiboken6 and pivy glue
that `patches/apply.sh` copies. Nothing in this repository ever created the other 1,847.
They were placed on the build machine by hand, survived in the runner's workspace, and at
some point went away. No gate noticed, because Part and PartDesign need none of it and the
boot smoke test uses exactly those.

**Fixed by:** `tools/stage-python-packages.sh`, run by the dependency lane, which builds the
tree from things the repository controls — the source trees the lanes already fetch, plus
pinned pip downloads of the pure-Python libraries — and fails loudly if any package is
missing rather than producing a partial tree.
**Guarded by:** the boot gate's `imports` scenario, which imports each of them in the real
browser and names the dead workbenches if any fails.



### R1. gmsh and CalculiX are not built against 1.1.3 *(blocker)*

`tools/publish-release.sh` carries `gmsh.{js,wasm}` and `ccx.{js,wasm}` over from the
previous release because they come from their own build lanes. Confirmed by asset sizes:
they are byte-for-byte the same as `build-20260813-eventstack`, an engine from before this
port. So every FEM workflow in the current release runs 1.0.x-era modules against a 1.1.3
engine, and that combination has never been executed.

They are separate wasm modules driven over a file-copy bridge, so it may well be fine — but
"may well be fine" is the thing this document exists to eliminate.

**Do:** rebuild both lanes against 1.1.3, publish them in the release, then mesh and solve
`FEMExample.FCStd` end to end and compare results against desktop FreeCAD.
**Watch for:** CalculiX reproducibility is only caught by comparing solver decks — compile
success, module size and stub counts all stay green while the solver is wrong.

### R2. `QEventLoop::exit` hits a null function on document restore *(blocker)*

Observed today on a clean local boot: the session-restore path
(`restored 1 document(s) from your last session`) throws
`RuntimeError: null function at QEventLoop::exit(int)`. The app survives and reaches Ready,
so it is not fatal — but it is an error thrown on one of the most common paths there is
(reopening the tab), and a null function pointer is never benign; it means a call landed on
an empty table slot.

**Diagnosed 2026-08-24, not yet fixed.** `tools/wasm-indirect-calls.py` shows that
`QEventLoop::exit` makes exactly one indirect call, through a *computed* index -- a
vtable load. So the empty slot is in an object, not in the code. Qt ends `exit()` by
calling `interrupt()` on the thread event dispatcher, which makes this a virtual call
on a **destroyed dispatcher**: a use-after-destroy, not a missing symbol.

The callers say when. Among them are `QMenu::~QMenu()`,
`ColorPickerPopup::~ColorPickerPopup()`, their `hideEvent` handlers and
`QDialogPrivate::setVisible` -- destructors exiting a nested event loop. A transient
popup torn down after the dispatcher has gone matches where this was seen: restoring a
session, where opening documents create and destroy transient widgets.

**Still open** because it does not reproduce headlessly, so nothing here is confirmed by
a failing test yet. The gate carries the detector, so a recurrence fails CI.

### R3. shiboken still owns `PyObject_GetBuffer` / `PyBuffer_Release` *(blocker)*

The same hazard class that cost this port its boot, one layer down. shiboken's limited-API
build defines both, and in this static monolith they win the symbols program-wide (wasm
indices 742/743, in shiboken's object cluster rather than CPython's). Unlike `PyMethod_New`
they do not depend on lazily initialised state, and `Pep_buffer` is a re-declaration of
`Py_buffer`, so this may be harmless — but it is unproven, and it is first suspect for any
failure in a memoryview, file or image path.

**Do:** rename them as `patches/pyside-setup.patch` does for the `pep384impl.cpp` group.
Deletion will not compile: shiboken's own call sites are typed against `Pep_buffer`.
Then add both to `RENAMED` in `tools/check-symbol-hijack.py`.

### R4. `QInputDialog` always returns "cancelled" — **not true any more; closed**

Inherited from ROADMAP Tier 1 #1 and measured against the running application rather than
re-read: the cancelling stub is gone from the JSPI dialog shim, a real modal opens
(`QInputDialog`, visible, 240×107, one line edit), and the value comes back —
`getText` returned `('typed-by-test', True)`, `getInt` returned `(42, True)`.

Kept as a gate scenario (`--scenario dialog`) rather than deleted, because this is a whole
class of feature — anything that asks for a name, a count or a length — and it broke
silently once already.

### R5. Documents can be evicted — **built; needs one human confirmation**

Losing a user's model is the worst failure this application can have, and worse than a
crash because it is silent. Checked what is actually there rather than assuming:

- the manifest meets Chrome's installability bar (name, short_name, start_url, standalone,
  192 and 512 icons including maskable) and `sw.js` registers with a fetch handler, so
  `beforeinstallprompt` has what it needs to fire;
- the install offer is deliberately deferred to the moment the user first saves real work,
  which is the only moment the ask is about something they would mind losing;
- when persistence is refused, the app warns in plain words and offers to mirror the work
  into a real folder on disk;
- both paths hang off `__fcWorkSaved`, which is called from the two real save routes
  (the OS save dialog and File > Save / Save As / Export). A scripted `saveAs` does not
  trigger them, which is correct.

What remains cannot be automated: headless Chromium has no install UI, so the grant itself
has to be confirmed by a person. Added to `MANUAL-QA.md` — install the app, then require
`navigator.storage.persisted()` to return `true`.

### R6. Nothing reports failures from the field — **the blind spot is closed**

Every failure class the user is shown is now also counted: `fcwebCrash` beacons `script`,
`rejection` or `other`, and wasm aborts keep their existing counter rather than being
counted twice. Verified in the running app — a synthetic rejection produced the toast and
exactly one `/t?e=crash&k=rejection`.

What is deliberately NOT sent: any message, stack, document name, identifier or free text.
The detailed diagnostic report stays on the user's clipboard, for them to attach to an
issue if they choose. A count is enough to know something is wrong and go looking, and
going further would trade a real privacy property for a convenience.

The original text of this item follows, for the record.

The counters added for boot/abort answer *how many*, never *what*. If a user hits R2 or an
OOM tomorrow, we learn nothing. Shipping "no known issues" without a way to hear about the
unknown ones is a statement about our visibility, not about the software.

### R7. The manual pass has never been run against this engine *(blocker)*

`MANUAL-QA.md` records its last result against `build-20260813-eventstack+c41d84b` — a
different engine, before the 1.1.3 port. Every line of that checklist is currently unverified
for what is live: workbench switching, sketching by clicking, Pad, property editing, task
panels, context menus, tree drag-and-drop, save/reload, STEP and STL round-trips, the OS file
dialog, and the bundled examples.

**Do:** run the full pass against the live build and record the result in `MANUAL-QA.md`.
Anything it finds joins this list before release.

---

## 2. Verify, then decide

These are unknowns rather than known defects. Each needs one measurement.

| # | Question | How to answer it |
|---|---|---|
| V1 | Does a returning visitor with a cached old engine get the new one? | Load the previous release, deploy this one, reload without clearing anything. `?v=<md5>` should bust it — but I hit a stale `fcweb-engine` cache locally today, so prove it end to end. |
| V2 | Did the 117 MB `FreeCAD.data` reduction lose anything? | **I answered "no" earlier today and I was wrong.** I checked the workbenches and the examples, found them present, and stopped. It lost the entire third-party Python stack — see R10. The lesson is in the failure: I verified the things I thought of, then reported a general conclusion. |
| V3 | Can the build be reproduced from a clean checkout? | **Already done, and this row was stale.** All three force-included headers -- `gl_compat.h`, `coin_intrusive.h`, `qprocess_stub.h` -- are tracked in `toolchain/include/`. Checked rather than assumed: `git ls-files toolchain/include` lists them. |
| V4 | Which dependency versions is production built from? | **Captured on every deps build.** `build-deps.yml` runs `tools/capture-dep-versions.sh` after the stack is built and uploads `deps-versions.txt`, so the answer is recorded by the only machine that can answer it, at the moment it finished. Asking a person to run it by hand and commit was never going to survive contact with a release. |
| V5 | Keep `--profiling-funcs` in production? | **Answered: keep it.** The raw 25.6 MB looked expensive; compressed it is not. Measured on the shipped binary: the name section is 14% of the raw wasm but costs **2.9 MB of the compressed download** (59.9 -> 57.0 MB), about 3% of an ~88 MB first load. Three per cent is not worth trading for crash reports that cannot name a function. |
| V6 | Does the 3D view render correctly on real hardware? | **The premise was wrong and the real obstacle is now identified.** Not "headless cannot render": rAF ticks 179 times in 3 s and SwiftShader gives a real WebGL2 context, and with `?gltrace=1` the app issues **399 draw calls** building one box -- 358 drawArrays, 41 drawElements, 20 of them in the main viewport (1014x549). Every capture still reads black because **Coin renders into a framebuffer object, not the canvas's default framebuffer**: screenshot, drawImage and `gl.readPixels` on the default FB all return 0 non-black even with `preserveDrawingBuffer: true` (added as `?pixelgate=1`, and confirmed present in getContextAttributes). So a pixel gate must read Coin's FBO, which the shell already does in `blit()`/`frameBlit()` behind `?overlay=1` -- that path did not activate in this configuration and is the next thing to chase. Nothing here needs a GPU or a build machine. |

---

## 3. Known limitations — document, do not pretend

These are real constraints. They should appear in the README and on the site before release,
so nobody discovers them as surprises.

- **Addon Manager is off.** It is a git submodule, and installing an addon assumes `git` plus
  a writable install tree via QProcess. A wasm-native path (fetch a zip, unpack into IDBFS)
  is a project, not a fix. *The single biggest gap against "usable by anyone".*
- **Addons with compiled extensions can never be installed.** One static monolith, inittab
  fixed at link time. Pure-Python addons can work; compiled ones cannot, by construction.
- **The Web workbench has no engine behind it** — Qt is built `-skip qtwebengine`.
- **Outbound HTTP is constrained by COEP.** Cross-origin isolation is required for threads,
  and under it most third-party hosts are refused. Anything reaching the wider web needs a
  same-origin proxy, which is not built.
- **~2 GB heap ceiling**, **Chrome/Edge 137+ only**, **CalculiX is single-threaded**.

---

## 4. Order of work

1. **R0 first.** Everything after it is verified by a machine instead of by memory, and
   without it any fix below can silently regress the way the boot did.
2. **R2, R3** — engine correctness, and both are cheap now that the naming tooling exists.
3. **R1** — the gmsh/ccx lanes and a real FEM run.
4. **R4, R5, R6** — the Tier 1 usability and durability items.
5. **R7** — the full manual pass, after the above, so it tests the release candidate rather
   than a moving target.
6. **Section 2** measurements, then the Section 3 documentation.
7. Re-run R7 on the final candidate. Release.

## What "release" should mean when we get there

- The R0 gate is green, and was proven to fail when the fix it guards is removed.
- `MANUAL-QA.md` carries a full pass against the exact build being released.
- Every item in Section 1 is closed, not deferred.
- Every item in Section 3 is written down where a user will see it before they rely on it.
