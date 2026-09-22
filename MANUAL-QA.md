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

**The wall, before anything else (2 min, Firefox and a phone)**
- [ ] In Firefox (or Safari): a full-screen "This needs Chrome or Edge on a desktop." page
      with two buttons, and in devtools' network tab NOTHING under `FreeCAD.*` was requested
- [ ] On a phone, any browser: "This needs a desktop or laptop." with a Copy-this-link button
- [ ] `?force=1` on the same phone skips the wall (that is the only way past it; never
      publish it)

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
      stray floating dock. Start any task (Part > Primitives): the panel must be visible
      OVER the 3D view, translucent with the mouse away, opaque with the mouse on it.
      Until 2026-09-13 the page painted the 3D frame on top of it and every task panel
      was invisible while Qt reported it shown; the 3D layer now goes under the UI layer.
- [ ] Box selection (View > Box selection, or Shift+B) and lasso: drag over part of the
      model. A translucent white rectangle with a thin yellow outline must follow the
      mouse over a frozen frame, and the release must select what it covered. Until
      2026-09-13 the band was drawn into a framebuffer nobody composited; the yellow
      outline is 1 px here where the desktop draws 4 px dashed (WebGL line width).

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
- [ ] **Save real work, then look for the storage offer.** After the first File > Save the
      app should either offer to install (which is the only way Chrome grants persistent
      storage) or, if it cannot, warn that the browser may clear your documents and offer a
      backup folder. Seeing neither means the one safeguard against silent data loss is not
      reaching users — the code paths exist and are wired to File > Save, but only a real
      browser can prove the offer appears.
- [ ] **Install it, then confirm persistence actually took.** With the app installed, run
      `navigator.storage.persisted()` in the console: it must return `true`. This cannot be
      tested headlessly — headless Chromium has no install UI — so it is checked here or
      nowhere, and until it returns true a user's documents can be evicted.

- [ ] **Save via the OS file dialog.** Chromium's `showSaveFilePicker` path cannot be
      scripted, so only a person can confirm the picker appears and the file lands where
      they chose. (The download fallback other browsers use is verified automatically.)
- [ ] **Choose a backup folder, then confirm files appear in it.** Same limitation:
      `showDirectoryPicker` needs a real user gesture and a real directory selection, so
      no script can complete it. Model something, wait ~20 s, and look in the folder with
      your file manager — a `.FCStd` should be there and should keep updating as you work.
      Then reload and confirm it reconnects without asking again. This is the mechanism
      that makes work survive the browser clearing its storage, so it is worth the minute.
- [ ] The axis cross in the corner shows small X, Y, Z letters next to its arrows, the
      same size as the desktop's (glPixelZoom; they drew three times too big for one link).
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

- [ ] **FEM, end to end.** Open FEMExample, or make a box with a fixed face and a force,
      mesh it (gmsh) and run CalculiX from the solver's task panel. The mesher and the solver
      each suspend the Python call while Qt's event loop keeps running; until 2026-09-13 that
      loop resumed on top of the suspended call's C stack, and the call came back to a
      smashed frame -- the result was written, then Python died with 'Fatal Python error:
      Executing a cache' and the page could freeze (the boot gate's post-fem hang). Every
      promising call now runs on its own stack. Expect: the result object appears, the colour
      map paints (per-vertex colours, a colour bar with a visible gradient AND its numbers
      beside it in DejaVu Sans -- every 2D label was invisible until 2026-09-14, when the
      raster shims were empty, and blocky until Coin got FreeType the same day), constraint
      arrows are arrow-sized, and NOTHING in the Report view mentions a fatal error.

**Sharing and MCP (5 min)** — only on a site running the optional `session` container
- [ ] **Edit > Share Session... starts a session and gives you a link.** The link appears in
      the field and the copy button lights up. Then open Edit > Preferences > Sharing: the
      pages are **General**, **Session** and **MCP**, in that order.
- [ ] **Open the link in a second browser profile** (a second Chrome profile, not a second
      tab of the same one). The watcher gets your document, and also your units and your
      theme — check a dimension reads in the same unit you use.
- [ ] **Edit something as the owner.** The watcher sees it within a few seconds. While it
      lands, the watcher's camera must NOT jump: they keep the view they were looking at,
      and they stay on the tab they were on.
- [ ] **The watcher's menu bar still works.** The editing commands are greyed out, but
      File, View, Tools, Windows and Help all open. A menu that will not open at all is a
      regression: read-only means the commands are disabled, not the menu bar.
- [ ] **Open a second document as the owner mid-session.** The watcher gets a second tab
      for it. Then edit one of them: the OTHER tab must not flash or redraw. Only the tab
      that changed changes.
- [ ] **Request control from the watcher, grant it as the owner.** The watcher's commands
      come back and the owner's grey out. Then take control back from the owner: it must
      return without the watcher having to do anything.
- [ ] **On the MCP page, press Enable assistant with no session started.** It starts one by
      itself rather than telling you to go to the General page first. Then press each copy
      button and paste what it gives you: both Claude Code and Codex put **two** lines on
      the clipboard, a remove followed by an add. One line means the remove was lost, and
      the second `add` will fail against an existing entry.
- [ ] **Close the owner's tab with the assistant connected.** Every tool now reports
      `no_tab`. The tools act inside the live tab, so no tab means no reach — the assistant
      must say so, not hang or answer from nothing.

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

    The a2plus click (1.5 s) is not a rendering cost: timed from inside the interpreter,
    the ray pick at the view centre is 170-230 ms (Coin's triangle walk over the picked
    body, Face4489 of a 34-part assembly), the selection with tree/property sync 50-190 ms,
    the clear 40-80 ms, one redraw 76 ms. The desktop does the same walk natively in a few
    tens of ms; on wasm it is the 42 MB file's one visible lag, and the everyday files
    click in 0.05-0.4 s.

Same table on 2026-09-12 morning, before the lighting-uniform cache, the merger cap and the
Coin sphere path: ArchDetail 19.9 s / 12.3 fps, BIMExample 18.6 s / 21.3 fps, EngineBlock
28.7 fps, AssemblyExample 27.4 fps. Console, WebGL and page errors: zero across the census
session (EngineBlock, a2plus, BIMExample, back) on the same engine.

## Measured on the dev tree -- 2026-09-13, engine 7836adcb (pivy type cache) + glue 72de0120

Same probe, same order, machine idle. pivy's autocast asked SWIG for "<Type> *" before
"So<Type> *" and SWIG caches hits only, so every getField/getChild from Python paid a
linear scan of every type table -- 55 us a call, 25,000 calls in a BIM open. patches/
pivy.patch remembers the answer; a call is 1.5-3 us now. Draft, Arch and BIM documents
are the ones that live on those calls, and it shows:

    FILE               OPEN s  DRAWS/frame  DRAG fps  press->frame s  click s  LOGS
    ArchDetail            6.4      2165        27.4        0.09        0.08     0
    AssemblyExample       0.8      1535        36.1        0.05        0.03     0
    BIMExample            7.1      1937        58.2        0.05        0.04     0
    EngineBlock           0.3      1478        37.8        0.03        0.05     0
    FEMExample            1.3      1453        33.8        0.28        0.04     0
    PartDesignExample     0.2       734        38.0        0.03        0.04     0
    draft_test_objects    0.7      1686        33.1        0.05        0.04     0
    Schenkel.stp          1.5       734        38.1        0.04        0.04     0
    a2plus (42 MB)       20.2      1442        25.5        0.14        0.32   136*
    SkyrimHelm (stl)      0.7      1411        52.2        0.04        0.04     0

Against the morning of 2026-09-12 (before the lighting-uniform cache, the merger cap, the
Coin sphere path, bytecode and this): ArchDetail 19.9 s / 12 fps -> 6.4 s / 27 fps,
BIMExample 18.6 s / 21 fps -> 7.1 s / 58 fps, a2plus 44 s -> 20 s with its click 0.9 ->
0.3 s, every other file under 1.6 s to open. What remains in ArchDetail, BIM and a2plus is
upstream work at wasm speed: the topological-naming ancestry build and OCC shape loading.
Console, WebGL and page errors: zero across the census session on this engine.

## Measured on the dev tree -- 2026-09-13, engine 4a6028d0 (bytecode in the payload) + glue 72de0120

Same probe, same order, machine idle. The payload now carries unchecked-hash bytecode for
every packaged Python tree (Python compiled 1,486 source files afresh on every boot before;
a cold `import Draft` was 1.6 s, now 0.36 s). Open times are what moved; the drags start
at the view centre as before.

    FILE               OPEN s  DRAWS/frame  DRAG fps  press->frame s  click s  LOGS
    ArchDetail           10.6      2141        17.1        0.14        0.17     0
    AssemblyExample       1.6      1466        34.8        0.06        0.05     0
    BIMExample           12.7      1868        40.7        0.08        0.06     0
    EngineBlock           0.6      1417        36.3        0.07        0.04     0
    FEMExample            2.2       762        32.4        0.07        0.07     0
    PartDesignExample     0.4       732        36.5        0.07        0.13     0
    draft_test_objects    1.2      1665        32.2        0.06        0.06     0
    Schenkel.stp          2.1       706        34.7        0.07        0.10     0
    a2plus (42 MB)       28.4      1418        33.9        0.21        0.50   136*
    SkyrimHelm (stl)      1.1      1393        48.3        0.06        0.06     0

Against the table below it: a2plus 71 -> 28 s and its click 1.5 -> 0.5 s, FEM 4.0 -> 2.2,
Schenkel 5.2 -> 2.1, draft 2.8 -> 1.2, SkyrimHelm 2.4 -> 1.1. ArchDetail and BIM opens
are flat at 10-13 s: their remaining time is the topological-naming ancestry build and
OCC shape loading, plus pivy's SWIG type lookups (next table). The payload grew from 200
to 307 MB uncompressed (about 99 MB gzipped) for it. A warm boot measured 12-15 s until
the overlay's filesystem gate stopped grepping the visible log for its marker (a boot
flood could trim the line out, and the gate then sat out its 15 s net with the app idle):
9.0 s to a revealed, active workbench on three consecutive warm boots after that fix.

## Measured on the dev tree -- 2026-09-14, engine 3cf06010 (FreeType in Coin, raster text) + glue e10df6aa

NOT an idle machine: another workload held the CPU at 45-90% for the whole session, so the
absolute numbers below are pessimistic and noisy (the same EngineBlock drag read 29 fps in one
cell and 57 in another an hour apart). What is load-independent: zero WebGL, console and page
errors across the census; every A/B in this session pixel-identical inside the 3D view.

    FILE               OPEN s   HEAP DRAWS DRAG fps  PRESS  CLICK   LOGS
    ArchDetail           17.4  1024M  2578     19.1   0.23   0.67     0/0
    AssemblyExample       2.9  1024M  1923     25.4   0.16   0.14     0/0
    BIMExample           31.0  1136M  2293     15.1   0.19   0.15     0/0
    EngineBlock           1.6  1136M  1872     26.9   0.19   0.44     0/0
    FEMExample            5.4  1136M  1994     32.8   0.06   0.08     0/0
    PartDesignExample     0.4  1136M   968     36.9   0.07   0.11     0/0
    draft_test_objects    1.0  1136M  2163     27.4   0.09   0.08     0/0
    Schenkel.stp          3.1  1136M   960     30.2   0.14   0.32     0/0
    a2plus               65.2  1751M  1915     21.6   0.52   1.37   136/68
    SkyrimHelm            2.3  1751M  1896     49.2   0.07   0.06     0/0

Same-session A/Bs (each pair back to back, so the load cancels out):

    ?vbofaces=1 (default) vs =0    AssemblyExample 46.7 vs 12.1 fps, FEM 33.2 vs 23.8,
                                   EngineBlock 44.8 vs 40.3, ArchDetail 22.4 vs 19.8; 0-0.14% px differ
    GL state shadow vs ?glshadow=0 EngineBlock 35.2 vs 29.4, ArchDetail 27.9 vs 27.8; 0 px differ

Where a frame goes now (EngineBlock drag, profiled): ~60 scene draws -- the geometry is
nearly free -- plus the axis cross (37 immediate-mode draws), Qt's raster repaint of the
widget layer, the present pass, and emscripten's per-access heap-view refresh
(growMemViews, 5.5% self). The two synchronous round trips that were left (glGetError x4 a
frame, getParameter on temp-buffer creation) are gone. Re-measure on an idle machine before
reading anything else into these numbers.

## Against DESKTOP FreeCAD 1.1.3 on the same machine -- 2026-09-14

The reference that was missing. The official Windows 1.1.3 installer (winget, hash-verified)
was extracted with 7-Zip into a scratch directory and run portably -- nothing installed --
with scratchpad/desk-bench.py: the same example files, the same stimulus as the web bench
(10 view-API changes, each followed by updateGui(); then 60 small camera rotations, one
frame each), same RTX 4080, same session, same 45-90% external CPU load on both. The web
numbers are this day's runs (bench-22 for the view changes, the analysis table and the
floor probe for drags); neither side had the machine to itself.

    FILE                DESKTOP view ms  WEB view ms   DESKTOP drag fps  WEB drag fps   DESKTOP open s  WEB open s
    ArchDetail                171            50              3.9            19-27           18.7          17.4
    draft_test_objects         73            52             13.3            27-32            1.8           1.0
    BIMExample                 12            37             75              15-40           17.8          31.0
    AssemblyExample             8            16            182              25-47            1.6           2.9
    EngineBlock                 4            34            244              27-57            0.6           1.6
    FEMExample                  3            59            259              33               2.3           5.4
    PartDesignExample           4            36            302              37-59            0.4           0.4
    empty document              -             -              -              45-52 (the floor)

Reading it: on the Draft-heavy files the web build is FASTER than the desktop on this
machine (ArchDetail 5-7x, draft_test_objects 2x -- the desktop spends its frame in
SoAsciiText/FreeType and immediate-mode dimension geometry that the web build batches). On
the light files the desktop renders an offscreen frame in 3-5 ms and the web build sits at
its ~20 ms per-frame floor (Qt repaint + compose + present, rAF-capped at 60): 4-6x in raw
frame time, both far above what a 60 Hz monitor shows. BIMExample is the one file where
the web build is genuinely behind (2-5x): Coin traversal at wasm speed. Opening times are
within 2x everywhere and equal on ArchDetail. Desktop drag numbers are uncapped offscreen
renders; on screen the desktop is vsync-limited like everything else.

## Display lists -- 2026-09-14 (engine 69f277f9, glue with the __fcDL recorder)

Coin's render caches were the desktop's advantage on static scenes and had never worked
here: glGenLists returned 0 since the first link, and two switches of our own (patch and
page) kept caching off so that Coin would not re-walk into empty caches every frame. The
glue now records every GL import between glNewList/glEndList (pointer data copied, client
arrays snapshotted, VBO draws as offsets, our own raster text ops re-evaluated at replay)
and glCallList replays it. Same session, same load, lists on vs ?dlists=0:

    FILE                lists on  lists off   px differ
    BIMExample             50.3      39.6        15
    draft_test_objects     50.2      40.6         0
    ArchDetail             32.0      27.0         0
    EngineBlock            53.4      52.8         0 (after the merger colour fix)
    AssemblyExample        58.1      53.9         0
    FEMExample             55.4      54.4       1-px label offsets on the colour bar
    PartDesignExample      55.3      59.2         0

Against the desktop table above: BIMExample 50 vs 75 (was 15-40), draft_test_objects 50
vs 13, ArchDetail 32 vs 4, the light files at the 60 Hz cap on both. What to look for:
edit a sketch, move an object, change a colour -- the change must show at once (a stale
cache would keep the old picture; Coin invalidates on every scene change and the probes
for sketching, Draft, FEM and box selection all pass). ?dlists=0 is the escape hatch and
turns caching off with it.

## Deferred GL teardown -- 2026-09-14 (glue 84a46c4, page 84a46c4)

With lists on, a BIMExample drag frame was still 13,672 WebGL calls for 657 draws: the
fixed-function emulation tore every batch down (disable attributes, useProgram(null),
bindBuffer(null)) and the next batch built it back up. The glue now defers the teardown to
the first point where someone could observe it, and the page shadow cancels a null program
bind, a null ARRAY_BUFFER bind and an attribute disable when the same state comes back
before a draw. ?lazyclean=0 and ?glshadow=0 are the escape hatches.

    BIMExample, same session         GPU-bound calls/frame   desk-bench drag (60 rotations)
    lazy + shadow (default)                  6,563             22.0 ms, 30.6 ms (two runs)
    ?lazyclean=0&glshadow=0                 12,338             28.0 ms, 46.9 ms

Pixel-identical against ?lazyclean=0 on BIMExample (twice), EngineBlock and
draft_test_objects; 0 console errors. Leaving pending attribute disables across a draw
was tried and rejected: ANGLE's D3D11 vertex path validates every enabled attribute (85
GL_INVALID_OPERATION on one redraw), so they are applied at the draw.

## In the user's own Chrome -- 2026-09-14

Two things the scripted probes never showed, seen through the Chrome extension on the
real browser (DPR 1.5, 1261x926 page):

- **The window never sized itself.** Boot took ~140 s under load and the page's
  window-state cycle (showNormal + showFullScreen, the fix for Qt creating its backing
  store before the device pixel ratio is known) gave up 120 s after page LOAD. Result: the
  app at 840x617 in the corner, raster UI at 1/dpr, the 3D view rect stale. Fixed in
  90b15ec: the bound runs from ready and the cycle is re-sent until FCDPR-DONE comes back.
  If you ever see the app small in the top-left, that is this.
- **Click flash (reported, open).** The user sees a black frame / another layer for an
  instant on every click in the 3D view; the probes never do. `?presentlog=1` records one
  entry per presented frame with the mean luminance of the composite; a hidden tab
  presents nothing, so the recording tab must be in front while the user clicks.

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

- Firefox, Safari, and every phone or tablet get the wall, not the app. The gate
  (`play-gui/freecad-gui.html`, "Browser support gate") compiles a 56-byte memory64 module
  and calls it through `WebAssembly.promising`; a browser that fails that, or answers a
  Number where a BigInt is required, cannot run this build whatever it claims about JSPI.
  `scratchpad/wall.js` is the check. Since 2026-09-21, after launch-day reports of
  "can't convert N to BigInt" from non-Chromium browsers.
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

- Lines look jagged: desktop FreeCAD 1.1.3 ships with anti-aliasing off (Preferences >
  Display > 3D View > Anti-Aliasing = None) and so do we. MSAA 2x-8x is available in the same
  dialog and costs frame rate; changing the shipped default is a product decision, not a bug.
- In the Addon Manager some READMEs never load (about 10 of 24 in the gate's sample): those
  are upstream 404s -- macros whose wiki page no longer exists, repositories whose default
  branch moved -- and desktop shows the same blanks. The proxy is not the cause; the rest of
  the catalogue, installs and download stats come through it.
- Wheel over the transparent part of the Tasks overlay scrolls the panel, not the 3D view.
  Desktop does the same unless the overlay is put in its transparent (mouse-through) mode.
- Add-ons that use `requests` (Ondsel Lens) work, and Chrome prints one line about a
  deprecated synchronous XMLHttpRequest on the main thread the first time one is sent.
  That is the transport (`/dev/fcweb-http`, see `play-gui/am/fcweb_requests.py`): the
  add-on blocks on the network exactly as it does on a desktop, from any context, and a
  sync XHR is the only browser primitive that can. Its `timeout=` is ignored (the browser
  forbids one) and redirects are followed by the browser. Lens's own "Listed" share-link
  parser trips over a link whose model carries no `attributes` (the add-on's dataclass
  requires it; the live API omits it on some entries) -- that reproduces on a desktop and
  belongs upstream. Login and workspaces need a Lens account; `scratchpad/lens.js` takes
  `LENS_EMAIL` / `LENS_PASSWORD` for that leg.
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
  live and can take control. Watchers see EVERY document the editor has open, as their own
  tabs, read-only, with the editing commands greyed out; they keep their own camera. The
  live view and the actions live in Edit > Preferences > Sharing > Session. The AI over MCP acts inside a
  live browser tab and inherits its rights; with no tab open, every tool says `no_tab`.

- Shared sessions run on the **wasm64** engine. The wasm64 link shipped on 2026-09-16, and
  on 2026-09-18 all six session scenarios (`share`, `empty`, `control`, `mcp`, `env`,
  `edges`) passed against it, as did the full 16-scenario regression sweep. The earlier
  note here, that the page on `dev` could not run against the released artifacts, is
  obsolete. The standing rule still holds: after ANY future link, re-run
  `boot-gate.py --scenario share|empty|control|mcp|env|edges` before believing sharing
  still works. They are not in `--scenario all` (each drives two browser contexts), so
  nothing else will run them for you.
