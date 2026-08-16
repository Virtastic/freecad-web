# freecad-web

**[FreeCAD](https://www.freecad.org) 1.0, compiled to WebAssembly and running in the browser.**
No install, no plugin, no server-side rendering — the real application, executing locally in
your tab.

👉 **<https://freecad.virtastic.app>**

This is not a viewer or a cut-down demo. It is upstream FreeCAD built for
`wasm32-emscripten` with wasm exceptions and JSPI: the same 20 workbenches, the same 578
commands, the same OCCT geometry kernel, the same CPython interpreter running the same
Python workbenches, and the same solvers.

> Not affiliated with or endorsed by the FreeCAD project. Please report problems here,
> not to FreeCAD upstream.

## What works

Verified under real mouse and keyboard input against production, not just scripted API calls:

- **All 20 workbenches** activate on first click; all 1111 declared toolbar items resolve to
  registered commands.
- **~500 of FreeCAD's own unit tests** pass (PartDesign, Part, Draft, Sketcher, Spreadsheet,
  Mesh, Arch, TechDraw, Assembly, Materials…).
- **Modelling**: sketch by clicking in the viewport, add dimensional constraints through the
  modal, pad through the task panel, boolean, fillet. Geometry agrees with closed-form
  answers — a PartDesign pad measured 8262.4 mm³ against an analytic 8262.4.
- **FEM end to end**: Gmsh meshes and CalculiX solves *in the browser*, validated to within
  1% of beam theory across solids, shells, beams, plane stress, contact, frequency, thermal
  and nonlinear.
- **Files**: open, save, save-as, export and import through FreeCAD's own menus —
  FCStd, STEP, IGES, STL, 3MF, OpenSCAD CSG, SVG, DXF.
- **Your work survives a reload.** Documents autosave to browser storage on edit and are
  restored on boot.

## Requirements and limits

These are real constraints, stated up front rather than discovered:

| | |
|---|---|
| **Browser** | Chrome or Edge 137+. Firefox and Safari lack JSPI; they are refused up front having downloaded nothing. |
| **First load** | ~139 MB. |
| **Memory** | A fixed 2 GB heap — roughly 20,000 simple solids. The app force-saves your documents and warns before it runs out. |
| **AddonManager** | Absent (it needs `git` and real sockets). A `.zip` / GitHub workbench installer covers the same use case. |
| **CalculiX** | Single-threaded, so large FEM jobs are slower than desktop. |

## Documentation

- **[BUILD-WEH.md](BUILD-WEH.md)** — how to reproduce the production build: toolchains, build
  order, linking, staging, deploy, and a frank record of every trap that cost real time.
- **[MANUAL-QA.md](MANUAL-QA.md)** — the 20-minute human pass, scoped to the three things
  automation is structurally blind to.
- **[AGENTS.md](AGENTS.md)** — the working agreements this project is developed under.
- **[infra/README.md](infra/README.md)** — serving and deployment.

## Building

The full build is a multi-hour, multi-gigabyte cross-compile of FreeCAD and its entire
dependency stack. [BUILD-WEH.md](BUILD-WEH.md) is the authority; start there.

The vendored source trees (`deps/`), toolchains (`emsdk/`, `qt/`) and build outputs are
gitignored. What this repository holds is everything needed to *recreate* them: the patch set
in [patches/](patches/), the configure and build scripts, the link commands, the front-end
shell in [play-gui/](play-gui/), and the verification harnesses in `scratchpad/`.

## License

LGPL-2.1-or-later, matching FreeCAD. See [LICENSE](LICENSE), and [NOTICE](NOTICE) for the
third-party components and their licenses — including Gmsh and CalculiX, which ship as
separate GPL WebAssembly modules rather than being linked in.
