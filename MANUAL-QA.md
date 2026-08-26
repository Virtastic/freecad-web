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

**Workbenches (3 min)** — the one that bit us
- [ ] Open the workbench dropdown and switch through **every** entry
- [ ] Each switch changes the toolbars *on the first click*
- [ ] Toolbar icons render (not blank squares), and tooltips appear on hover

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
- [ ] Open one of the bundled examples (BIM is the heaviest — watch for slowness)

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

- Chrome/Edge 137+ only (other browsers are refused up front, having downloaded nothing)
- First load downloads ~115 MB. Later loads really are cached now — the engine is held in
  Cache Storage, so a return visit fetches **nothing** and reaches Ready in seconds.
  (It genuinely was not cached before 2026-08-16: Chrome's HTTP cache will not retain a
  152 MB entry, so every visit re-downloaded the lot. If you see a return visit downloading
  again, that is a regression worth reporting.)
- AddonManager is absent (use the `.zip` / GitHub workbench installer)
- Memory is a fixed 2 GB, with a civil message if a model exhausts it
- CalculiX solves are single-threaded, so large FEM jobs are slower than desktop
