# The 20-minute manual pass

Everything in this repo is verified by script, including real mouse and keyboard input.
The scripts are still blind to three things, and only a person sitting in front of it can
close them:

1. **Whether it looks right.** A script asserts a line exists at (14.8, -22.5). It cannot
   tell you the line is invisible, the wrong colour, or drawn a centimetre from the cursor.
2. **Whether it feels right.** Nothing measures "the drag lags half a second" or "the
   button highlighted but nothing happened for two seconds".
3. **Whether a real sequence holds together.** Scripts reset between checks. A person
   doing ten things in a row hits state that no isolated check reaches.

The bar for shipping is not "no crashes" — it is "a CAD user would not immediately notice
something is off".

## Why this matters more than it sounds

On 2026-08-13, **CAM and OpenSCAD were both dead on the first click** — the workbench
selector did nothing, and clicking again worked. At that moment ~500 upstream unit tests
passed, eight workbenches loaded, six examples opened, and every harness in this repo was
green. A person opening the workbench menu would have found both in ten seconds.

## What the machine already checked, so you do not have to

`tools/boot-gate.py --scenario workflow` runs on every link and asserts the parts of this
pass that are fact rather than judgement. Measured against the live engine:

- a **constrained** rectangle sketch solves to **zero degrees of freedom** and pads to
  exactly 10000.0 mm3 as a valid solid -- the constraint solver and PartDesign together;
- cut / fuse / common all return valid shapes, with common at exactly 216.0;
- a STEP export re-reads with the same volume and six faces;
- an STL round trip returns the same facet count;
- a document saves, closes, reopens, and its pad still measures 10000.0.

So the list below is now about what a machine cannot judge: whether it LOOKS right,
whether it FEELS responsive, and whether the mouse does what a hand expects. Spend the
twenty minutes there.

## The pass, in order (each line is one thing to try)

Open https://freecad.virtastic.app in Chrome or Edge, and watch for anything that looks
wrong rather than anything that errors.

**Boot and first impression (2 min)**
- [ ] The window looks like FreeCAD — menus, toolbars, tree, 3D view all where they belong
- [ ] No blank panels, overlapping widgets, clipped text, or missing icons
- [ ] The splash/loading step ends and the app is responsive, not merely painted
- [ ] The loader goes straight to the finished window. Until 2026-09-11 it dropped onto a
      bare four-menu window (File Edit View Help, no toolbars) that filled in seconds
      later and then flashed and resized; it now waits for the workbench and that resize.
      Seeing the bare window again is a regression.
- [ ] The "Tasks" panel sits on the RIGHT as a translucent overlay (title bar with the
      task boxes, e.g. PartDesign's "Start Part / New Body"). That is upstream 1.1's
      default layout (`OverlayWidgets.cpp` seeds the right overlay with "Tasks"), not a
      stray floating dock.

**Workbenches (3 min)** — the one that bit us
- [ ] Open the workbench dropdown and switch through **every** entry
- [ ] Each switch changes the toolbars *on the first click*
- [ ] Toolbar icons render (not blank squares), and tooltips appear on hover. Surface and
      Inspection had blank buttons until 2026-09-12 (their Qt resources were never
      registered in the static link); the CAM workbench logged "No module named 'yaml'" on
      activation until the same day (PyYAML is now staged with the other pure-Python
      packages). Either coming back is a regression in the link or the Python tree.

**Modelling (5 min)**
- [ ] Part: create a Box, orbit / pan / zoom — smooth, no stutter, no flicker
- [ ] The nav cube responds and reorients the view
- [ ] PartDesign: sketch a rectangle **by clicking**, close it, Pad it
- [ ] While sketching: the line follows the cursor, snaps read sensibly, geometry is visible
- [ ] The pad appears with correct shading and edges

**Panels and dialogs (3 min)**
- [ ] Select the pad: the property editor fills, and editing a value applies it
- [ ] Open a task panel (e.g. Pad), type a length, press OK — the model updates
- [ ] Escape closes menus; clicking away also closes them
- [ ] Right-click the tree and the 3D view: menus appear near the cursor and are readable
- [ ] **Help > About opens a dialog**, and its OK button closes it (this was dead until
      2026-08-13: a dialog opened by mouse could not suspend, so nothing appeared at all)
- [ ] **Drag a tree item onto a Group** and drop it — it should reparent. This is the one
      interaction no script can drive: Chrome refuses to begin a native HTML5 drag from
      synthesised input, and Qt's wasm drag is built on native drag events. The pipeline
      is verified (`scratchpad/dragsim.js` dispatches the drag events itself and the drop
      reparents), but only a human hand proves Chrome starts the gesture.

**Files and persistence (4 min)**
- [ ] Save the document, reload the browser tab, reopen it — geometry intact
- [ ] Export a STEP and an STL; open the STEP back
- [ ] - [ ] **Save real work, then look for the storage offer.** After the first File > Save the
      app should either offer to install (which is the only way Chrome grants persistent
      storage) or, if it cannot, warn that the browser may clear your documents and offer a
      backup folder. Seeing neither means the one safeguard against silent data loss is not
      reaching users — the code paths exist and are wired to File > Save, but only a real
      browser can prove the offer appears.
- [ ] **Install it, then confirm persistence actually took.** With the app installed, run
      `navigator.storage.persisted()` in the console: it must return `true`. This cannot be
      tested headlessly — headless Chromium has no install UI — so it is checked here or
      nowhere, and until it returns true a user's documents can be evicted.

**Save via the OS file dialog** — Chromium's `showSaveFilePicker` path cannot be
      scripted, so only a person can confirm the picker appears and the file lands where
      they chose. (The download fallback other browsers use is verified automatically.)
- [ ] **Choose a backup folder, then confirm files appear in it.** Same limitation:
      `showDirectoryPicker` needs a real user gesture and a real directory selection, so
      no script can complete it. Model something, wait ~20 s, and look in the folder with
      your file manager — a `.FCStd` should be there and should keep updating as you work.
      Then reload and confirm it reconnects without asking again. This is the mechanism
      that makes work survive the browser clearing its storage, so it is worth the minute.
- [ ] Open one of the bundled examples (BIM is the heaviest — watch for slowness). Since
      2026-09-12 the edges are drawn from a cached array by default (`?vboedges=0` goes
      back to one call per vertex): measured on the dev tree, EngineBlock drag-rotates at
      27-45 fps, BIMExample 48, and the 42 MB a2plus assembly 37-65 -- if a drag feels like
      single digits, that is a regression. Black edges on Part shapes and the object's own
      LineColor on everything else; a red-edged box must have red edges.
      ArchDetail is the draw-count case (Draft dimensions: ~95 sphere dots, text labels,
      ~2,500 draws a frame): it dragged at 6 fps until the GL emulation stopped re-sending
      all 37 lighting uniforms on every draw (same day, tools/patch-freecad-js.py), 19 fps
      after, pixel-identical. Its dots are also spheres that Coin drew as 15 flushes each;
      the Coin patch draws each as one array (patches/coin3d.patch). If ArchDetail drags in
      single digits again, one of those two came undone.
- [ ] A file whose Python proxies are not installed (the a2plus assembly) pops the
      notification list over the 3D view -- one warning per blocked object, same as the
      desktop. Escape or a click dismisses it; the model behind it is fine.

**Feel (3 min)**
- [ ] Nothing takes visibly longer than it should for the size of the model
- [ ] No moment where the UI is frozen with no indication of progress
- [ ] Text is crisp, not blurry, at your display's scaling

## Recorded result — 2026-08-16, build `build-20260813-eventstack+c41d84b`

Driven against **production**, in a real browser, with the results below measured rather
than asserted. This covers the automatable half; the two human-only checks (starting a
native drag, and the `showSaveFilePicker` dialog) are **still outstanding** and are the
reason this file exists.

| check | result |
|---|---|
| cold boot to Ready | 23 s |
| return visit to Ready | 8–10 s, **0 bytes fetched** for wasm/data |
| workbench first-click activation | **19/19**, 0 failures (incl. CAM and OpenSCAD) |
| PartDesign sketch → pad | 1400.000 mm³ vs analytic 1400.000 — **0.0000%** |
| boolean cut (box − cylinder) | 717.257 mm³ vs analytic 717.257 — **0.0000%** |
| STEP export | 8291 bytes written |
| File → Save (anchor path) | file delivered, `_dl` staging left **empty** |
| autosave observer installed | marker present |
| **work survives a reload** | `SurviveReload/Brick vol=4199.0` restored (13×17×19) |
| memory monitor | live, heap 285 MB at idle |
| GL tracer off by default | `window.__gllog` undefined |
| console errors | none |

Two things this pass caught that no scripted API test would have:

1. **Autosave was never installing.** `FreeCAD._fcweb_saver` did not exist, the autosave
   directory was empty, and every failure path was a swallowed exception, so it looked
   healthy. A user could have modelled for an hour and lost everything.
2. **A GL-tracer gate had disabled three unrelated subsystems** — autosave, the
   out-of-memory warning, and the draw-call batching — because an early return skipped the
   rest of the enclosing IIFE. The app looked completely normal.

Both are fixed and re-verified above. The lesson for future passes: check that a subsystem
is *alive*, not merely that nothing threw.

## Measured against PRODUCTION -- 2026-08-26, build serving since 25 Aug 01:38

Run with `tools/boot-gate.py --base-url https://freecad.virtastic.app`, which drives the
live site rather than an artifact. This replaces a recorded pass from 2026-08-16 against
`build-20260813-eventstack`, an engine from before this port. Everything below is what the
deployed build does today, measured:

| scenario | live result |
|---|---|
| serving contract (`ci/jenkins/smoke-test.sh`) | **ok** -- COOP, COEP, wasm mime, legal.html, LICENSE |
| boot | **ok** -- Ready in 14-19 s, `Part::Box` volume 6000.0, App.Version 1.1.3 |
| workflow | **ok** -- pad 10000.0, sketch DoF 0, boolean 216.0, STEP round-trip, survives reload |
| workbenches | **ok** -- 20 activated, 0 failed |
| dialogs | **ok** -- the typed value comes back |
| openUrl | **ok** -- reaches the browser |
| restore | **FAILS** -- autosave writes `RestoreProbe.FCStd`, and the reload restores nothing (`docs: []`) |
| imports | **FAILS** -- numpy, matplotlib, PIL, ifcopenshell, pivy.coin, femmesh.gmshtools, Draft all absent |
| fem | **FAILS** -- `ModuleNotFoundError: No module named 'numpy'` at femmesh/meshtools.py:30 |
| examples | **FAILS** -- FEMExample.FCStd traps the engine (`RuntimeError: unreachable`) |
| addons | **FAILS** -- `No module named 'NetworkManager'`; the workbench is not in this build |

So the live site models, sketches, pads, cuts, round-trips STEP and switches workbenches --
and cannot do FEM, Draft, BIM or Plot, loses work on reload, and crashes on one of its own
examples. Every one of those has a fix built and waiting on the pending release; none of
them is new, and none had been measured against production until now.

## Measured on the dev tree -- 2026-09-12, engine 1210cd4b (Coin sphere arrays) + glue 3728f892

One headed Chrome, real GPU, dpr 1.5, 1707x932, every bundled example plus the two files in
the download folder, opened in one session in this order (scratchpad/gpu-analysis.py; the
drag starts at the view centre, so an object under the cursor is preselected while dragging,
which is the everyday case). Machine idle (CPU under 20 percent) when it ran.

    FILE               OPEN s  DRAWS/frame  DRAG fps  press->frame s  click s  LOGS
    ArchDetail           10.8      2591        30.8        0.17        0.45     0
    AssemblyExample       1.5      1578        34.2        0.06        0.05     0
    BIMExample           11.8      1922        46.8        0.06        0.05     0
    EngineBlock           0.5      1426        34.9        0.06        0.11     0
    FEMExample            4.0      1336        32.5        0.17        0.04     0
    PartDesignExample     0.7       642        23.8        0.11        0.31     0
    draft_test_objects    2.8      1482        18.0        0.19        0.17     0
    Schenkel.stp          5.2       530        21.0        0.19        0.37     0
    a2plus (42 MB)       71.3      1360        21.1        0.52        1.51   136*
    SkyrimHelm (stl)      2.4      1284        28.6        0.20        0.32     0

    * all 136 are the a2plus proxy ImportErrors the desktop prints too (addon not installed).

Same table on 2026-09-12 morning, before the lighting-uniform cache, the merger cap and the
Coin sphere path: ArchDetail 19.9 s / 12.3 fps, BIMExample 18.6 s / 21.3 fps, EngineBlock
28.7 fps, AssemblyExample 27.4 fps. Console, WebGL and page errors: zero across the census
session (EngineBlock, a2plus, BIMExample, back) on the same engine.

## What the gate now checks, so you do not have to

`tools/boot-gate.py --scenario all` runs on every link and covers these lines mechanically,
in a real browser, against the exact artifact being released:

| checklist line | scenario | what it asserts |
|---|---|---|
| the app starts | `boot` | Ready, and a `Part::Box` with volume 6000.0 |
| work survives a reload | `restore` | a document written before the reload comes back with its geometry |
| deploying while a tab is open | `upgrade` | the previous engine's document opens in the new engine, URLs stamped as the deploy stamps them |
| workbench first-click activation | `workbenches` | every workbench activates -- 20/20 today |
| sketch, pad, boolean, STEP/STL | `workflow` | pad 10000.0, sketch DoF 0, boolean valid, round-trip volume matches |
| dialogs return a value | `dialog` | the typed value comes back, not a cancel |
| third-party Python | `imports` | numpy, matplotlib, PIL, ifcopenshell, pivy, femmesh, Draft |
| reaching the web | `network` | a real cross-origin GET through the same-origin proxy, driven by Qt |
| FEM end to end | `fem` | gmsh meshes and CalculiX solves, within 5% of the closed form |
| the bundled examples | `examples` | all seven open, and a wasm trap is reported as a trap |

What is left for a person is what a person is actually needed for: starting a native drag,
the `showSaveFilePicker` dialog, the PWA install and its storage grant, and whether the
thing looks and feels right. Those are the sections above.

## What to write down

For anything that looks or feels wrong, note **what you did, what you expected, what you
saw**. A screenshot beats a description. "Fillet preview flickers while dragging" is
actionable; "3D view is janky" is not.

## Known and accepted — not worth reporting

- The browser console should be EMPTY. The last line it used to carry -- "WebGL: this
  extension has very low support on mobile devices ... WEBGL_polygon_mode", Chrome's note
  the first time a context asks for the polygon-mode extension -- is gone since 2026-09-12:
  the app asks for the extension only when a filled polygon is actually drawn in wireframe,
  and on every bundled sample and the a2plus assembly the draws issued in wireframe mode
  are all lines already. Seeing that line means a document really draws faces as wireframe
  (a Wireframe-styled Mesh, say); it is still not an error.
- A file whose Python proxies belong to an addon that is not installed (the a2plus
  assembly, `a2p_*`) logs one "module not permitted" line per object in the Report View,
  exactly as desktop FreeCAD 1.1 does for the same file.
- "OpenSCAD executable not found" when the OpenSCAD workbench activates: there is no
  OpenSCAD binary in a browser, and a desktop without it installed prints the same line.
  Switching through all 20 workbenches on a clean boot logs nothing else (2026-09-12,
  after the asyncio shim let CAM's asset manager initialise: 14 tool bits, no errors).

- Chrome/Edge 137+ only (other browsers are refused up front, having downloaded nothing)
- First load downloads ~115 MB. Later loads really are cached now — the engine is held in
  Cache Storage, so a return visit fetches **nothing** and reaches Ready in seconds.
  (It genuinely was not cached before 2026-08-16: Chrome's HTTP cache will not retain a
  152 MB entry, so every visit re-downloaded the lot. If you see a return visit downloading
  again, that is a regression worth reporting.)
- Memory grows to a 16 GB ceiling (where V8 caps wasm64 memory), with a civil message if a model
  exhausts it. It was a fixed 2 GB until the growable link shipped; the page's own
  pressure monitor divided by the heap's CURRENT size until 2026-09-02 and so announced
  "2 GB" long after the build had stopped being limited to it.
- CalculiX solves are single-threaded, so large FEM jobs are slower than desktop
- Opening and closing many documents in one session used to exhaust WebGL contexts (one
  per 3D view, never released; from the sixteenth document Chrome evicted the oldest, which
  could be the window's own). Fixed 2026-09-11: Qt was destroying the context all along, but
  the page's present-pass registries and the glue's object tables kept references that
  stopped the browser reclaiming it. `scratchpad/gpu-context-churn.py`: 24 contexts over
  twenty documents, 0 lost (was losing one per document from the sixteenth).
- Shared sessions and MCP exist only where the operator runs the optional `session` container
  (`docker compose --profile share up -d`). Without it, Edit → Share Session… says so and
  nothing else changes; a `?s=` link on such a site opens FreeCAD normally with one toast.
  Sharing is turn-taking, not concurrent editing: one person edits, everyone else watches
  live (following the editor's camera) and can take control. The AI over MCP acts inside a
  live browser tab and inherits its rights; with no tab open, every tool says `no_tab`.

- Shared sessions were verified against the **wasm32** engine that v1.0.0 and play-gui
  actually hold. `dev` has since moved the page to wasm64 (`BigInt` pointers) ahead of any
  published wasm64 link, so the page on `dev` -- session code or not -- cannot run against
  the released artifacts until that link ships. When it does, re-run
  `boot-gate.py --scenario share|mcp|control|env|edges` before believing sharing still works.
