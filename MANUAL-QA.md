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

**Files and persistence (4 min)**
- [ ] Save the document, reload the browser tab, reopen it — geometry intact
- [ ] Export a STEP and an STL; open the STEP back
- [ ] Open one of the bundled examples (BIM is the heaviest — watch for slowness)

**Feel (3 min)**
- [ ] Nothing takes visibly longer than it should for the size of the model
- [ ] No moment where the UI is frozen with no indication of progress
- [ ] Text is crisp, not blurry, at your display's scaling

## What to write down

For anything that looks or feels wrong, note **what you did, what you expected, what you
saw**. A screenshot beats a description. "Fillet preview flickers while dragging" is
actionable; "3D view is janky" is not.

## Known and accepted — not worth reporting

- Chrome/Edge 137+ only (other browsers are refused up front, having downloaded nothing)
- First load is ~139 MB; later loads are cached
- AddonManager is absent (use the `.zip` / GitHub workbench installer)
- Memory is a fixed 2 GB, with a civil message if a model exhausts it
- CalculiX solves are single-threaded, so large FEM jobs are slower than desktop
