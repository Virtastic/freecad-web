# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) Virtastic
"""Start the built application in a real browser and make it do CAD work. Fail if it cannot.

    python tools/boot-gate.py <dir>                       # boot + geometry
    python tools/boot-gate.py <dir> --scenario restore     # + save, reload, restore
    python tools/boot-gate.py <dir> --scenario all --expect-version 1.1.3

THE GAP THIS CLOSES

For the whole of the 1.1.3 port the application could not start, and every gate was green.
CI compiled it, linked it, validated the wasm, checked the GL patch table, checked the
exception model, counted archive symbols, and deployed -- without ever running the program.
The bug was found because a person opened the page. Worse, the fix for it had been written
in an earlier session behind `#ifdef FCWEB_REAL_CPYTHON`, a macro defined nowhere in the
repository, so it was inert for months and nothing noticed.

So this gate does the one thing none of the others did: it runs the thing.

SCENARIO boot
  1. the page reaches Ready (window.__fcAppReady, set from Qt's onLoaded, i.e. after
     main() has initialised the interpreter);
  2. no Fatal Python error, no Aborted(), no wasm trap;
  3. FreeCAD's own Python builds real geometry: a Part::Box 10x20x30 must recompute to
     volume 6000.0 with 8 vertices and 6 faces -- interpreter, bindings and OCCT kernel
     together, which is exactly what the boot bug broke;
  4. App.Version() is the version we think we shipped;
  5. all of it inside a time budget, because a hang is a failure and not a wait.

SCENARIO restore -- the half a fresh profile can never test
  A new browser profile has no saved work, so scenario `boot` never exercises the restore
  path at all. That path is where a returning user's documents come back, and it is where
  a null-function trap in QEventLoop::exit was seen by hand. This scenario keeps ONE
  browser profile across two loads: make a document, wait for autosave to write it and for
  IDBFS to persist it, then load again and require that the app says it restored the work
  and that no trap fired. It also proves autosave installed at all -- which is how ?no3d
  was caught silently disabling it.

The 3D viewport is off by default (?no3d). Headless GL is not the GL a user has, so a
rendering verdict from here would look like coverage while proving something else;
rendering stays a human check (RELEASE-PLAN.md V6). Pass --with-3d to override.
"""
import argparse
import base64
import io
import json
import ast
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time

SMOKE_PY = r'''
import FreeCAD as App, Part, sys as _s
_d = App.newDocument("BootGate")
_b = _d.addObject("Part::Box", "Box")
_b.Length = 10; _b.Width = 20; _b.Height = 30
_d.recompute()
_sh = _b.Shape
_v = App.Version()
_s.__stderr__.write("FCGATE " + repr({
    "volume": _sh.Volume,
    "verts": len(_sh.Vertexes),
    "faces": len(_sh.Faces),
    "version": _v[0] + "." + _v[1] + "." + _v[2],
    "docs": len(App.listDocuments()),
}) + "\n")
_s.__stderr__.flush()
'''

MAKE_DOC_PY = r'''
import FreeCAD as App, sys as _s
_d = App.newDocument("RestoreProbe")
_b = _d.addObject("Part::Box", "Box")
_b.Length = 12; _b.Width = 8; _b.Height = 5
_d.recompute()
_d.saveAs("/home/web_user/RestoreProbe.FCStd")
_s.__stderr__.write("FCMADE ok\n")
_s.__stderr__.flush()
'''

DIALOG_PY = r'''
# Prompt-driven workflows are a whole class of feature: anything that asks for a name, a
# count or a length. A stub here once made every one of them take the cancel branch and
# quietly do nothing, so drive a real modal and require the typed value back.
import sys as _s
try:
    from PySide6 import QtWidgets, QtCore

    def _accept():
        dlg = QtWidgets.QApplication.activeModalWidget()
        if dlg is None:
            _s.__stderr__.write("FCDIALOG {'ok': False, 'why': 'no modal appeared'}\n")
            _s.__stderr__.flush()
            return
        for e in dlg.findChildren(QtWidgets.QLineEdit):
            e.setText("typed-by-gate")
        dlg.accept()

    QtCore.QTimer.singleShot(1500, _accept)
    _v, _ok = QtWidgets.QInputDialog.getText(None, "gate", "Name:")
    _s.__stderr__.write("FCDIALOG " + repr({"ok": bool(_ok), "value": _v}) + "\n")
    _s.__stderr__.flush()
except Exception as _e:
    _s.__stderr__.write("FCDIALOG " + repr({"ok": False, "why": repr(_e)}) + "\n")
    _s.__stderr__.flush()
'''

IMPORTS_PY = r'''
# The inittab is a promise; an import is the delivery. Every one of these has its C
# half linked into the binary, and each needs a Python package on the filesystem to be
# reachable. Shipping one half of numpy is the same as shipping none of it.
import sys as _s
_res = {}
for _n in ('numpy', 'matplotlib', 'PIL', 'ifcopenshell', 'pivy.coin', 'femmesh.gmshtools', 'Draft'):
    try:
        __import__(_n)
        _res[_n] = 'ok'
    except Exception as _e:
        _res[_n] = type(_e).__name__
_s.__stderr__.write('FCIMPORTS ' + repr(_res) + chr(10))
_s.__stderr__.flush()
'''

FEM_PY = r'''
# FEM end to end: mesh a solid with gmsh and solve it with CalculiX, both separate wasm
# modules reached over a JSPI bridge -- and then check the ANSWER.
#
# "It ran" is not a result. Every failure this scenario exists to catch reported success:
# the mesher shim whose waitForFinished was shadowed by a stub returning True, the wasm
# branch that returned rc=0 having written no file, and the threaded ccx that solved a
# matrix of zeros. So this compares the solved displacement against the closed form and
# fails on a number rather than on an exception.
#
# The case is a 100 x 20 x 20 mm steel bar, fixed at one end and pulled normal to the
# other. That is pure tension, so delta = F*L/(E*A) exactly -- no mesh-refinement caveat,
# which is why it is used here instead of a cantilever.
import sys as _s

_NL = chr(10)
_out = {}
try:
    import FreeCAD as App
    import ObjectsFem
    from femmesh.gmshtools import GmshTools

    doc = App.newDocument("FemGate")
    box = doc.addObject("Part::Box", "Box")
    box.Length, box.Width, box.Height = 100.0, 20.0, 20.0
    doc.recompute()

    analysis = ObjectsFem.makeAnalysis(doc, "Analysis")
    solver = ObjectsFem.makeSolverCalculiXCcxTools(doc, "CalculiX")
    analysis.addObject(solver)
    mat = ObjectsFem.makeMaterialSolid(doc, "Steel")
    md = mat.Material
    md["Name"] = "Steel-Generic"
    md["YoungsModulus"] = "210000 MPa"
    md["PoissonRatio"] = "0.30"
    md["Density"] = "7900 kg/m^3"
    mat.Material = md
    analysis.addObject(mat)
    fixed = ObjectsFem.makeConstraintFixed(doc, "Fixed")
    fixed.References = [(box, "Face1")]
    analysis.addObject(fixed)
    force = ObjectsFem.makeConstraintForce(doc, "Force")
    force.References = [(box, "Face2")]
    force.Force = 100000.0                 # FreeCAD's internal force unit; 100 N
    force.Reversed = True
    analysis.addObject(force)
    fm = ObjectsFem.makeMeshGmsh(doc, "Mesh")
    fm.Shape = box
    fm.CharacteristicLengthMax = "15 mm"
    analysis.addObject(fm)
    doc.recompute()

    GmshTools(fm).create_mesh()
    _out["nodes"] = fm.FemMesh.NodeCount
    _out["volumes"] = fm.FemMesh.VolumeCount
    if not fm.FemMesh.NodeCount:
        raise RuntimeError("gmsh produced no mesh")

    from femtools import ccxtools

    fea = ccxtools.FemToolsCcx(analysis, solver)
    fea.update_objects()
    fea.setup_working_dir()
    fea.setup_ccx()
    fea.purge_results()
    fea.write_inp_file()
    fea.ccx_run()
    fea.load_results()

    # The load the deck actually carries. Lines beginning "**" are comments and sit
    # INSIDE *CLOAD, so they must not be mistaken for the start of a new section.
    total, rows, section = 0.0, 0, None
    with open(fea.inp_file_name, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            t = line.strip()
            if t.startswith("**") or not t:
                continue
            if t.startswith("*"):
                section = t.upper()
                continue
            if section and section.startswith("*CLOAD"):
                parts = [p.strip() for p in t.split(",")]
                if len(parts) >= 3:
                    try:
                        total += abs(float(parts[2]))
                        rows += 1
                    except ValueError:
                        pass
    _out["cloadRows"] = rows
    _out["loadN"] = round(total, 6)

    res = None
    for o in doc.Objects:
        if o.isDerivedFrom("Fem::FemResultObject"):
            res = o
    if res is None:
        raise RuntimeError("the solver produced no result object")
    disp = list(res.DisplacementLengths or [])
    mx = max(disp) if disp else 0.0
    analytic = total * 100.0 / (210000.0 * 400.0)      # F*L/(E*A)
    _out["maxDisplacementMm"] = round(mx, 9)
    _out["analyticMm"] = round(analytic, 9)
    _out["ratio"] = round(mx / analytic, 4) if analytic else 0.0
except Exception as _e:
    import traceback

    _out["error"] = "%s: %s" % (type(_e).__name__, _e)
    _out["where"] = traceback.format_exc().strip().splitlines()[-3][:160]
_s.__stderr__.write("FCFEM " + repr(_out) + _NL)
_s.__stderr__.flush()
'''

EXAMPLES_PY = r'''
# Every example the Start page offers, opened. These are the first thing a new user
# clicks, they ship inside the payload, and nothing checked that they open.
#
# FEMExample.FCStd did not: it trapped the engine with "RuntimeError: unreachable" inside
# vtkXMLParser::GetXMLByteIndex on the .vtu it carries, because a VTK patch that had been
# written to prevent exactly that was never applied. A trap is not an exception -- Python
# does not see it, the promise rejects, and from the page it looks like nothing happened.
# So this reports per file and treats "did not come back" the same as "raised".
import os
import sys as _s

_NL = chr(10)
_res = {}
try:
    import FreeCAD as App

    d = "/freecad/share/examples"
    names = sorted(f for f in os.listdir(d) if f.endswith(".FCStd"))
    for n in names:
        _s.__stderr__.write("FCEXAMPLE-TRY " + n + _NL)
        _s.__stderr__.flush()
        try:
            doc = App.openDocument(os.path.join(d, n))
            _res[n] = "ok:%d" % len(doc.Objects)
            App.closeDocument(doc.Name)
        except Exception as e:
            _res[n] = "%s: %s" % (type(e).__name__, str(e)[:70])
except Exception as e:
    _res["*"] = "%s: %s" % (type(e).__name__, str(e)[:90])
_s.__stderr__.write("FCEXAMPLES " + repr(_res) + _NL)
_s.__stderr__.flush()
'''

WORKBENCHES_PY = r'''
# Activate every workbench the build ships. This is the largest line in MANUAL-QA and the
# one most likely to rot quietly: a workbench that fails to activate does not crash the
# app, it just is not there when someone reaches for it -- and the import that failed is
# swallowed into the report view where nobody is looking.
#
# activate() is what clicking the selector does, so this is the same path a person takes.
import sys as _s

_NL = chr(10)
_res = {}
try:
    import FreeCADGui as Gui

    names = sorted(Gui.listWorkbenches().keys())
    for n in names:
        try:
            Gui.activateWorkbench(n)
            _res[n] = "ok"
        except Exception as e:
            _res[n] = "%s: %s" % (type(e).__name__, str(e)[:60])
except Exception as e:
    _res["*"] = "%s: %s" % (type(e).__name__, str(e)[:90])
_s.__stderr__.write("FCWB " + repr(_res) + _NL)
_s.__stderr__.flush()
'''

ADDON_INSTALL_PY = r'''
# Install an addon, for real: fetch a zip through this origin's proxy with Qt's own
# network stack, unpack it into the IDBFS-backed Mod directory, and put it on sys.path.
# That is the whole of the Addon Manager's no-git path, driven directly.
#
# It is driven directly rather than through the workbench because the two can fail
# independently: the workbench's PySideWrapper imports five Qt modules in one statement and
# reports the same message whichever is missing, which says nothing about whether an
# install would work. This measures the mechanism.
import io as _io
import os
import sys as _s
import zipfile

_NL = chr(10)
_out = {}
try:
    _s.path.append("/freecad/Mod/AddonManager")
except Exception:
    pass
try:
    from PySide6 import QtCore, QtNetwork

    URL = "https://codeload.github.com/FreeCAD/FreeCAD-macros/zip/refs/heads/master"
    try:
        import NetworkManager
        rewritten = NetworkManager.fcweb_proxy_url(URL)
        _out["viaWorkbenchRewrite"] = True
    except Exception as e:
        _out["viaWorkbenchRewrite"] = "%s: %s" % (type(e).__name__, str(e)[:60])
        rewritten = URL.replace("https://codeload.github.com", "/proxy/codeload")
    _out["url"] = rewritten

    nam = QtNetwork.QNetworkAccessManager()
    reply = nam.get(QtNetwork.QNetworkRequest(QtCore.QUrl(rewritten)))
    loop = QtCore.QEventLoop()
    reply.finished.connect(loop.quit)
    QtCore.QTimer.singleShot(180000, loop.quit)
    loop.exec()
    _out["httpError"] = str(reply.error())
    blob = bytes(reply.readAll())
    _out["bytes"] = len(blob)
    if len(blob) < 1000:
        raise RuntimeError("too small to be a zip (%d bytes)" % len(blob))

    dest = "/home/web_user/.local/share/FreeCAD/Mod"
    os.makedirs(dest, exist_ok=True)
    z = zipfile.ZipFile(_io.BytesIO(blob))
    names = z.namelist()
    z.extractall(dest)
    root = os.path.join(dest, sorted(n.split("/")[0] for n in names)[0])
    _out["installedTo"] = root
    pys = []
    for dirpath, _dirs, files in os.walk(root):
        pys += [f for f in files if f.endswith(".py")]
    _out["pyFiles"] = len(pys)
    if not pys:
        raise RuntimeError("unpacked with no Python in it")
    _s.path.insert(0, root)
except Exception as e:
    _out["error"] = "%s: %s" % (type(e).__name__, str(e)[:120])
_s.__stderr__.write("FCADDONINSTALL " + repr(_out) + _NL)
_s.__stderr__.flush()
'''

ADDON_PRESENT_PY = r'''
# After the reload: is the addon still on disk? An install that does not survive a reload
# is not an install, it is a download.
import os
import sys as _s

_NL = chr(10)
_out = {}
try:
    dest = "/home/web_user/.local/share/FreeCAD/Mod"
    _out["mods"] = sorted(os.listdir(dest)) if os.path.isdir(dest) else []
    pys = 0
    for d in _out["mods"]:
        for dirpath, _dirs, files in os.walk(os.path.join(dest, d)):
            pys += len([f for f in files if f.endswith(".py")])
    _out["pyFiles"] = pys
except Exception as e:
    _out["error"] = "%s: %s" % (type(e).__name__, str(e)[:90])
_s.__stderr__.write("FCADDONPRESENT " + repr(_out) + _NL)
_s.__stderr__.flush()
'''

RENDER_PY = r'''
# Build one box and fit the view, so there is something on screen to measure.
import sys as _s

_NL = chr(10)
try:
    import FreeCAD as App
    import FreeCADGui as Gui

    doc = App.newDocument("RenderGate")
    b = doc.addObject("Part::Box", "Box")
    b.Length, b.Width, b.Height = 40.0, 25.0, 15.0
    doc.recompute()
    Gui.activeDocument().activeView().viewAxonometric()
    Gui.SendMsgToActiveView("ViewFit")
    _s.__stderr__.write("FCRENDER {'built': True}" + _NL)
except Exception as _e:
    _s.__stderr__.write("FCRENDER " + repr({'built': False, 'error': repr(_e)}) + _NL)
_s.__stderr__.flush()
'''

# Does NEAR geometry hide FAR geometry? -- the assertion the colour histogram cannot make.
#
# On 2026-09-02 every building in the BIM example rendered see-through from the second
# frame on: the frame-end GL state reset disabled GL_DEPTH_TEST behind Coin's back and
# Coin's lazy cache never re-enabled it, so interiors drew over facades. The render gate
# above passed the whole time -- a depth-less scene still fills a healthy fraction of the
# frame with plenty of distinct colours, which is all it checks.
#
# So: a SMALL RED box sitting completely inside the silhouette of a LARGE GREEN box behind
# it, green added second so it draws second. With depth working, red survives. With depth
# off, green paints over it and red vanishes. Colours are compared by hue dominance rather
# than exact RGB, because the shaded pixel value is a lighting and rasteriser detail.
# Do the page's own GL registries still grow without bound?
#
# The present pass keeps a framebuffer registry (REG) and an upload list (UPL), and it
# walks REG once per FRAME. Until 2026-09-02 neither was pruned on delete: every 3D view
# a session ever opened left ~6 dead framebuffer entries behind, so the per-frame scan
# grew with the number of documents ever opened and the page bound deleted framebuffers
# (the staged build's gate log was full of "bindFramebuffer: attempt to use a deleted
# object"). None of that is visible from outside a closure, which is how it survived, so
# the page exposes window.__fcPresentStats() and this asserts on it.
LEAK_PY = r'''
# Open and close documents, each of which builds and tears down a 3D view.
import sys as _s

_NL = chr(10)
try:
    import FreeCAD as App
    import FreeCADGui as Gui

    for _i in range(8):
        _d = App.newDocument("LeakProbe%d" % _i)
        _d.addObject("Part::Box", "B")
        _d.recompute()
        Gui.updateGui()
        App.closeDocument(_d.Name)
        Gui.updateGui()
    _s.__stderr__.write("FCLEAK {'cycled': True}" + _NL)
except Exception as _e:
    _s.__stderr__.write("FCLEAK " + repr({'cycled': False, 'error': repr(_e)}) + _NL)
_s.__stderr__.flush()
'''

OCCLUDE_PY = r'''
# Two boxes, one behind the other, to prove that depth testing is on.
import sys as _s

_NL = chr(10)
try:
    import FreeCAD as App
    import FreeCADGui as Gui

    doc = App.newDocument("DepthGate")
    # Sized so the near box is a LARGE share of the far box's silhouette (40x40 inside
    # 90x90, so ~25% of the visible green when depth works). The first version used a
    # 10x10 near box, whose ~1.2% share sat below the gate's own threshold and failed on
    # a build that was rendering correctly -- the check has to have room between "visible"
    # and "hidden", not just a non-zero count.
    near = doc.addObject("Part::Box", "Near")
    near.Length, near.Width, near.Height = 40.0, 40.0, 10.0
    near.Placement.Base = App.Vector(15.0, 15.0, 60.0)
    near.ViewObject.ShapeColor = (1.0, 0.0, 0.0)

    # Added second, so Coin traverses (and draws) it second. Big enough that its
    # silhouette swallows the near box from this viewpoint.
    far = doc.addObject("Part::Box", "Far")
    far.Length, far.Width, far.Height = 90.0, 90.0, 10.0
    far.Placement.Base = App.Vector(-20.0, -20.0, -40.0)
    far.ViewObject.ShapeColor = (0.0, 1.0, 0.0)

    doc.recompute()
    v = Gui.activeDocument().activeView()
    v.setCameraType("Orthographic")     # no perspective foreshortening to reason about
    v.viewTop()                         # look straight down: near is directly over far
    Gui.SendMsgToActiveView("ViewFit")
    _s.__stderr__.write("FCDEPTH {'built': True}" + _NL)
except Exception as _e:
    _s.__stderr__.write("FCDEPTH " + repr({'built': False, 'error': repr(_e)}) + _NL)
_s.__stderr__.flush()
'''

# Read the frame the viewport actually produced.
#
# Coin renders into its OWN offscreen FBO and the C++ blits that into Qt's backing FBO, so
# the canvas default framebuffer is black by construction -- screenshots, drawImage and
# readPixels on it all return nothing while the app is drawing perfectly well. ?pixelgate=1
# keeps the drawing buffer and records each WebGLFramebuffer OBJECT as it is bound (an id
# cannot be resolved to an object: emscripten's GL map is not exported). Read those.
READ_FRAME_JS = r"""(() => {
  const gl = window.__fcPixelGl, all = window.__fcPixelFbos || [];
  if (!gl) return JSON.stringify({error: 'pixelgate did not install (is ?pixelgate=1 set?)'});
  const l = document.getElementById('load'); if (l) l.style.display = 'none';
  const prev = gl.getParameter(gl.READ_FRAMEBUFFER_BINDING);
  let best = null;
  for (let i = 0; i < all.length; i++) {
    try {
      gl.bindFramebuffer(gl.READ_FRAMEBUFFER, all[i]);
      const W = 1000, H = 520, buf = new Uint8Array(W * H * 4);
      gl.readPixels(0, 0, W, H, gl.RGBA, gl.UNSIGNED_BYTE, buf);
      const cols = {};
      for (let p = 0; p < buf.length; p += 4) {
        const k = buf[p] + ',' + buf[p + 1] + ',' + buf[p + 2];
        cols[k] = (cols[k] || 0) + 1;
      }
      const total = W * H;
      const bg = cols['247,247,247'] || 0;
      // Hue dominance, for the occlusion check: which of two coloured solids reached the
      // frame. Compared as "clearly redder than green" rather than an exact RGB, because
      // the shaded value depends on lighting and on the rasteriser.
      let reddish = 0, greenish = 0;
      for (let p = 0; p < buf.length; p += 4) {
        const r = buf[p], g = buf[p + 1], b2 = buf[p + 2];
        if (r > g + 40 && r > b2 + 40) reddish++;
        else if (g > r + 40 && g > b2 + 40) greenish++;
      }
      const rec = {
        distinct: Object.keys(cols).length,
        total: total,
        background: bg,
        nonBackground: total - bg,
        reddish: reddish,
        greenish: greenish,
        top: Object.entries(cols).sort((a, b) => b[1] - a[1]).slice(0, 6),
      };
      if (!best || rec.distinct > best.distinct) best = rec;
    } catch (e) { /* not every framebuffer is readable */ }
  }
  gl.bindFramebuffer(gl.READ_FRAMEBUFFER, prev);
  return JSON.stringify(best || {error: 'no readable framebuffer'});
})()"""

SAVE_MAKE_PY = r'''
# A document with a volume nobody could produce by accident, so the file that comes back
# out can be checked against it rather than merely existing.
import sys as _s

_NL = chr(10)
_out = {}
try:
    import FreeCAD as App

    doc = App.newDocument("SaveProbe")
    b = doc.addObject("Part::Box", "Brick")
    b.Length, b.Width, b.Height = 13.0, 17.0, 19.0     # 4199, and not a round number
    doc.recompute()
    _out["volume"] = round(b.Shape.Volume, 3)
    _out["label"] = doc.Label
except Exception as e:
    _out["error"] = "%s: %s" % (type(e).__name__, str(e)[:120])
_s.__stderr__.write("FCSAVEMAKE " + repr(_out) + _NL)
_s.__stderr__.flush()
'''

SAVE_ACTIVATE_PY = r'''
# Make SaveProbe the active document, immediately before the download.
#
# File > Save saves FreeCAD.ActiveDocument, which is correct. What is not obvious is that
# something else can become active between creating a document and saving it: the app
# restores the previous session's autosaved document, that restore finishes asynchronously,
# and it activates what it restored. In --scenario all this raced and lost -- the gate
# built a 4199 box, hit save, and was handed the 6000 box the boot scenario had left
# behind. The readback check caught it, which is the reason the readback check exists.
#
# So the activation is made explicit here and reported, rather than assumed.
import sys as _s

_NL = chr(10)
_out = {}
try:
    import FreeCAD as App

    for _d in App.listDocuments().values():
        if _d.Label == "SaveProbe":
            App.setActiveDocument(_d.Name)
            break
    _a = App.ActiveDocument
    _out["active"] = _a.Label if _a else None
    _out["open"] = sorted(d.Label for d in App.listDocuments().values())
except Exception as e:
    _out["error"] = "%s: %s" % (type(e).__name__, str(e)[:120])
_s.__stderr__.write("FCSAVEACT " + repr(_out) + _NL)
_s.__stderr__.flush()
'''

SAVE_REOPEN_PY = r'''
# Reopen the bytes the BROWSER was handed, not the copy still in memory. Anything less
# proves the app can write a file, not that a user can leave with one.
import sys as _s

_NL = chr(10)
_out = {}
try:
    import FreeCAD as App

    _p = "/home/web_user/_readback.FCStd"
    d = App.openDocument(_p)
    _out["objects"] = len(d.Objects)
    for o in d.Objects:
        if getattr(o, "TypeId", "") == "Part::Box":
            _out["volume"] = round(o.Shape.Volume, 3)
except Exception as e:
    _out["error"] = "%s: %s" % (type(e).__name__, str(e)[:120])
_s.__stderr__.write("FCSAVEBACK " + repr(_out) + _NL)
_s.__stderr__.flush()
'''

# What the browser will tell us about durability, and what the app does when the answer is
# no. navigator.storage.persist() cannot be granted headlessly -- Chrome ties it to
# installation and engagement -- so this records the state rather than demanding one, and
# then checks the branch that a real user on a fresh visit actually gets.
STORAGE_STATE_JS = r"""() => new Promise((resolve) => {
  const out = {hasApi: !!(navigator.storage && navigator.storage.persisted)};
  if (!out.hasApi) { resolve(JSON.stringify(out)); return; }
  navigator.storage.persisted().then((p) => {
    out.persisted = p;
    const est = navigator.storage.estimate ? navigator.storage.estimate() : Promise.resolve({});
    return est.then((e) => {
      out.quotaMB = e.quota ? Math.round(e.quota / 1048576) : null;
      out.usageMB = e.usage ? Math.round(e.usage / 1048576) : null;
      resolve(JSON.stringify(out));
    });
  }).catch((e) => { out.error = String(e); resolve(JSON.stringify(out)); });
})"""

# Drive the refusal branch directly. fcwebWarnEvictable is what the app calls the moment a
# user saves real work, and on a browser that has not granted persistence it must say so.
WARN_EVICTABLE_JS = r"""() => new Promise((resolve) => {
  const host0 = document.getElementById('fcweb-toasts');
  const before = host0 ? host0.children.length : 0;
  if (typeof window.fcwebWarnEvictable !== 'function') {
    resolve(JSON.stringify({error: 'fcwebWarnEvictable is not defined'})); return;
  }
  window.fcwebWarnEvictable();
  setTimeout(() => {
    const host = document.getElementById('fcweb-toasts');
    const kids = host ? Array.from(host.children) : [];
    resolve(JSON.stringify({
      before: before,
      after: kids.length,
      text: kids.map((k) => (k.textContent || '').trim()).join(' | ').slice(0, 300),
      buttons: kids.map((k) => Array.from(k.querySelectorAll('button'))
                                    .map((b) => b.textContent.trim())).flat(),
    }));
  }, 1200);
})"""

SWIGBRIDGE_PY = r'''
# The exact call that produced a black viewport, in isolation.
#
# Every existing scenario builds geometry through C++ view providers, which never cross
# FreeCAD's SWIG bridge -- which is why a build where the bridge was dead passed all
# thirteen of them and still drew nothing when a user opened a project. The failing path is
# a PYTHON view provider handing a pivy coin node to C++:
#
#     File "/freecad/Mod/Assembly/JointObject.py", line 1070, in attach
#         vobj.addDisplayMode(self.display_mode, "Wireframe")
#     RuntimeError: No SWIG wrapped library loaded
#
# FreeCAD converts that coin node with Base::Interpreter().createSWIGPointerObj, which walks
# the SWIG runtimes compiled into the binary. SWIG stamps its type table with a
# version-specific key, so a FreeCAD built against one SWIG and a pivy built against another
# never see each other and every conversion throws.
#
# This does the conversion and nothing else.
import sys as _s

_NL = chr(10)
_out = {}
try:
    import FreeCAD as App
    import FreeCADGui as Gui
    from pivy import coin

    _out["pivy"] = "ok"
    doc = App.newDocument("SwigProbe")
    obj = doc.addObject("App::FeaturePython", "Probe")
    vp = obj.ViewObject
    if vp is None:
        _out["error"] = "no ViewObject (is the GUI up?)"
    else:
        sep = coin.SoSeparator()
        sep.addChild(coin.SoSphere())
        # THE call. If the bridge is dead this raises RuntimeError.
        vp.addDisplayMode(sep, "Wireframe")
        _out["addDisplayMode"] = "ok"
        # Read it back through a view provider that actually DECLARES the mode.
        #
        # An earlier version read listDisplayModes() off a bare App::FeaturePython and got
        # [] -- which looked like a silent no-op and was carried for hours as an unexplained
        # loose end. It is not a defect: the default view provider's getDisplayModes()
        # returns nothing, so the list is empty however well addDisplayMode worked. The
        # readback is only meaningful against a provider that declares the mode, so this
        # attaches one and asks it.
        try:
            class _VP:
                def __init__(self, o):
                    o.Proxy = self
                def attach(self, o):
                    o.addDisplayMode(coin.SoSeparator(), "FcwebProbe")
                def getDisplayModes(self, o):
                    return ["FcwebProbe"]
                def getDefaultDisplayMode(self):
                    return "FcwebProbe"

            o2 = doc.addObject("App::FeaturePython", "Probe2")
            _VP(o2.ViewObject)
            doc.recompute()
            _out["modes"] = list(o2.ViewObject.listDisplayModes())
        except Exception as e:
            _out["modes"] = "unreadable: %s: %s" % (type(e).__name__, str(e)[:80])
except Exception as e:
    _out["error"] = "%s: %s" % (type(e).__name__, str(e)[:160])
_s.__stderr__.write("FCSWIG " + repr(_out) + _NL)
_s.__stderr__.flush()
'''

# What does the USER see?
#
# READ_FRAME_JS searches window.__fcPixelFbos, and the pixelgate hook only records a
# framebuffer when `if (fb)` -- i.e. only OFFSCREEN ones. The default framebuffer, which is
# what Qt composites into and what the page canvas presents, is never in that list.
#
# So every rendering gate this project has ever run measured Coin's private buffer. On
# 2026-08-27 production drew 744 distinct colours into that buffer while users saw a black
# screen, and the gate passed. Coin was rendering perfectly; the COMPOSITE from its FBO to
# the canvas was broken by a framebuffer feedback loop. A check that reads the buffer
# before the broken step cannot see the broken step.
#
# This reads framebuffer 0. With ?pixelgate=1 the context is created with
# preserveDrawingBuffer, so the composited frame is still there to be read.
READ_CANVAS_JS = r"""(() => {
  const gl = window.__fcPixelGl;
  if (!gl) return JSON.stringify({error: 'pixelgate did not install (is ?pixelgate=1 set?)'});
  const l = document.getElementById('load'); if (l) l.style.display = 'none';
  const prev = gl.getParameter(gl.READ_FRAMEBUFFER_BINDING);
  try {
    gl.bindFramebuffer(gl.READ_FRAMEBUFFER, null);        // THE DEFAULT FRAMEBUFFER
    const W = Math.min(gl.drawingBufferWidth || 0, 1200);
    const H = Math.min(gl.drawingBufferHeight || 0, 700);
    if (!W || !H) return JSON.stringify({error: 'canvas has no drawing buffer'});
    const buf = new Uint8Array(W * H * 4);
    gl.readPixels(0, 0, W, H, gl.RGBA, gl.UNSIGNED_BYTE, buf);
    const cols = {};
    let opaque = 0;
    for (let p = 0; p < buf.length; p += 4) {
      if (buf[p + 3] > 8) { opaque++; }
      const k = buf[p] + ',' + buf[p + 1] + ',' + buf[p + 2];
      cols[k] = (cols[k] || 0) + 1;
    }
    const keys = Object.keys(cols);
    keys.sort((a, b) => cols[b] - cols[a]);
    const total = W * H;
    // "Black" here means literally the dominant colour is near-black and almost nothing
    // else is present -- which is the reported symptom, not a proxy for it.
    const domCount = cols[keys[0]] || 0;
    const dom = keys[0].split(',').map(Number);
    return JSON.stringify({
      w: W, h: H, total: total,
      distinct: keys.length,
      dominant: keys[0],
      dominantPct: Math.round(1000 * domCount / total) / 10,
      dominantIsDark: (dom[0] + dom[1] + dom[2]) < 60,
      opaquePct: Math.round(1000 * opaque / total) / 10,
      top: keys.slice(0, 3).map(k => k + ' x' + cols[k]),
    });
  } catch (e) {
    return JSON.stringify({error: String(e).slice(0, 140)});
  } finally {
    try { gl.bindFramebuffer(gl.READ_FRAMEBUFFER, prev); } catch (e) {}
  }
})"""

# WHAT IS ON TOP OF THE PAGE?
#
# A screenshot proves the window is black. It does not say why, and the two candidates
# need completely different fixes: nothing was DRAWN, or something is COVERING it.
#
# Qt draws the menus and toolbars, Coin does not -- so a black frame that includes the
# menus, taken while Coin's own buffer holds 740 distinct colours, is far more consistent
# with a cover than with a drawing failure.
DOM_STACK_JS = r"""(() => {
  const out = {
    nativeComposite: window.__fcNativeComposite,
    coinFbo: window.__fcCoinFbo,
    big: [],
  };
  for (const el of document.querySelectorAll('body *')) {
    const r = el.getBoundingClientRect();
    if (r.width < 300 || r.height < 200) { continue; }
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden') { continue; }
    out.big.push(el.tagName + (el.id ? '#' + el.id : '')
                 + ' ' + Math.round(r.width) + 'x' + Math.round(r.height)
                 + ' pos=' + cs.position + ' z=' + cs.zIndex
                 + ' op=' + cs.opacity + ' bg=' + cs.backgroundColor);
  }
  const cx = Math.round(window.innerWidth / 2), cy = Math.round(window.innerHeight / 2);
  out.atCentre = (document.elementsFromPoint ? document.elementsFromPoint(cx, cy) : [])
    .slice(0, 6)
    .map(el => el.tagName + (el.id ? '#' + el.id : ''));
  // Collect canvases from the document AND from every open shadow root -- Qt-for-wasm keeps
  // its own canvas inside #qt-shadow-container, where querySelectorAll cannot reach.
  const cans = [];
  const walk = (root) => {
    for (const c of root.querySelectorAll('canvas')) { cans.push(c); }
    for (const el of root.querySelectorAll('*')) {
      if (el.shadowRoot) { walk(el.shadowRoot); }
    }
  };
  walk(document);
  out.canvases = cans.map(c => {
    const r = c.getBoundingClientRect();
    // THE QUESTION: has this canvas been handed to a worker? Once
    // transferControlToOffscreen has been called, getContext throws on this thread --
    // which is exactly what "Qt renders somewhere else" looks like from here.
    let ctx = 'none';
    try {
      const g = c.getContext('webgl2', {}) || c.getContext('webgl', {});
      ctx = g ? 'webgl-live' : 'null';
    } catch (e) {
      ctx = 'THROWS: ' + String(e && e.name || e).slice(0, 40);
    }
    return (c.id || '(no id)') + ' css=' + Math.round(r.width) + 'x' + Math.round(r.height)
           + ' buf=' + c.width + 'x' + c.height + ' getContext=' + ctx;
  });
  // Is the Qt shadow root OPEN or CLOSED? walk() can only descend into open roots, so
  // a closed one means every canvas inside it was invisible to the count above -- and
  // "there is only one canvas" would be an artefact of the probe, not a fact.
  out.shadowRoots = Array.from(document.querySelectorAll('*'))
    .filter(el => el.id || el.tagName === 'DIV')
    .slice(0, 40)
    .map(el => (el.id || el.tagName) + '=' + (el.shadowRoot ? 'OPEN' : 'none/closed'))
    .filter(x => /qt|screen|shadow/i.test(x));
  out.crossOriginIsolated = window.crossOriginIsolated;
  out.hardwareConcurrency = navigator.hardwareConcurrency;
  out.pixelGlSameCanvas = (() => {
    try {
      const g = window.__fcPixelGl;
      if (!g || !g.canvas) { return 'no pixelgate gl'; }
      return cans.indexOf(g.canvas) >= 0
        ? 'pixelgate gl IS one of the page canvases (index '
          + cans.indexOf(g.canvas) + ' of ' + cans.length + ')'
        : 'pixelgate gl canvas is NOT among the page canvases';
    } catch (e) { return 'err ' + e; }
  })();
  return JSON.stringify(out);
})"""

GL_RESET_JS = r"""(() => {
  const gl = window.__fcPixelGl;
  if (!gl) { return 'no pixelgate gl'; }
  try {
    gl.useProgram(null);
    gl.bindBuffer(gl.ARRAY_BUFFER, null);
    gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, null);
    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, null);
    gl.bindRenderbuffer(gl.RENDERBUFFER, null);
    gl.bindFramebuffer(gl.FRAMEBUFFER, null);
    gl.disable(gl.DEPTH_TEST);
    gl.disable(gl.BLEND);
    gl.disable(gl.CULL_FACE);
    gl.disable(gl.SCISSOR_TEST);
    gl.disable(gl.STENCIL_TEST);
    gl.depthMask(true);
    gl.colorMask(true, true, true, true);
    gl.frontFace(gl.CCW);
    for (let i = 0; i < 8; i++) { try { gl.disableVertexAttribArray(i); } catch (e) {} }
    if (gl.bindVertexArray) { try { gl.bindVertexArray(null); } catch (e) {} }
    let n = 0;
    while (gl.getError() !== gl.NO_ERROR && n < 64) { n++; }
    return 'reset done, cleared ' + n + ' latched error(s)';
  } catch (e) {
    return 'reset threw: ' + String(e).slice(0, 120);
  }
})"""

DRAW_COUNT_INSTALL_JS = r"""(() => {
  const gl = window.__fcPixelGl;
  if (!gl) { return 'no pixelgate gl'; }
  if (window.__fcDrawStats) { return 'already installed'; }
  const st = {toCoinFbo: 0, toZero: 0, toOther: 0, errors: 0, lastOtherFbo: null};
  window.__fcDrawStats = st;
  const wrap = (name) => {
    const orig = gl[name];
    if (typeof orig !== 'function') { return; }
    gl[name] = function (...a) {
      let fb = null;
      try { fb = gl.getParameter(gl.FRAMEBUFFER_BINDING); } catch (e) {}
      const r = orig.apply(gl, a);
      // A bound framebuffer object is not a number, so compare identity against the one
      // Coin published rather than trying to read its GL name back.
      const coin = window.__fcCoinFboObj || null;
      if (fb === null) { st.toZero++; }
      else if (coin && fb === coin) { st.toCoinFbo++; }
      else { st.toOther++; st.lastOtherFbo = String(fb); }
      try { if (gl.getError() !== gl.NO_ERROR) { st.errors++; } } catch (e) {}
      return r;
    };
  };
  ['drawArrays', 'drawElements', 'drawArraysInstanced', 'drawElementsInstanced'].forEach(wrap);
  // Remember which framebuffer object Coin binds, so its draws can be told apart.
  const ob = gl.bindFramebuffer;
  gl.bindFramebuffer = function (t, f) {
    try { if (f && window.__fcCoinFbo && !window.__fcCoinFboObj) { window.__fcCoinFboObj = f; } }
    catch (e) {}
    return ob.call(gl, t, f);
  };
  return 'installed';
})"""

DRAW_COUNT_READ_JS = r"""(() => JSON.stringify(window.__fcDrawStats || {none: true}))"""

PROJECT3D_PY = r'''
# Open a shipped example that carries PYTHON view providers, and fit it in the view.
#
# Assembly and Draft objects build their scene graph from Python: a view provider makes a
# pivy coin node and hands it to C++. That path crosses FreeCAD's SWIG bridge and, on the
# way to the screen, the native composite. Every OTHER scenario builds geometry through
# C++ view providers (Part::Box, PartDesign, the FEM mesh), which touch neither -- which is
# exactly why three separate rendering faults shipped on 2026-08-27 with all thirteen
# scenarios green:
#
#   1. FreeCAD and pivy built against different SWIG runtimes, so every
#      addDisplayMode(coinNode, ...) threw "No SWIG wrapped library loaded"
#   2. the legacy overlay's state was declared in a scope that had closed, so blit threw
#      ReferenceError into its own catch, every frame, silently
#   3. fcTex left bound while Coin rendered into the FBO it is attached to -- a framebuffer
#      feedback loop, undefined behaviour, and it drew nothing
#
# All three produced a black viewport and none was visible to a gate.
import os
import sys as _s

_NL = chr(10)
_out = {}
try:
    import FreeCAD as App
    import FreeCADGui as Gui

    d = "/freecad/share/examples"
    # Prefer a file that carries Python view providers. ArchDetail and BIMExample are Draft
    # /Arch; AssemblyExample is Assembly. Fall back to whatever is there.
    prefer = ["AssemblyExample.FCStd", "ArchDetail.FCStd", "BIMExample.FCStd"]
    names = sorted(f for f in os.listdir(d) if f.endswith(".FCStd"))
    pick = next((p for p in prefer if p in names), names[0] if names else None)
    if not pick:
        _out["error"] = "no examples on disk"
    else:
        _out["file"] = pick
        doc = App.openDocument(os.path.join(d, pick))
        doc.recompute()
        _out["objects"] = len(doc.Objects)
        # How many objects actually got a scene graph? A view provider that threw leaves
        # the object present and invisible, which is the failure being hunted.
        vis = 0
        for o in doc.Objects:
            try:
                if o.ViewObject is not None and o.ViewObject.Visibility:
                    vis += 1
            except Exception:
                pass
        _out["visible"] = vis
        try:
            Gui.activeDocument().activeView().viewAxonometric()
            Gui.SendMsgToActiveView("ViewFit")
        except Exception as e:
            _out["view"] = "%s: %s" % (type(e).__name__, str(e)[:80])
except Exception as e:
    _out["error"] = "%s: %s" % (type(e).__name__, str(e)[:140])
_s.__stderr__.write("FCPROJ3D " + repr(_out) + _NL)
_s.__stderr__.flush()
'''

NETWORK_PY = r'''
# Can the application reach the web at all? Under COEP:require-corp a direct cross-origin
# fetch is refused however co-operative the remote server is, so everything has to go
# through this origin's /proxy. This drives Qt's own network stack -- the same one the
# Addon Manager uses -- rather than the browser's fetch, because that is what has to work.
import sys as _s
try:
    from PySide6 import QtCore, QtNetwork

    _nam = QtNetwork.QNetworkAccessManager()
    _url = QtCore.QUrl("/proxy/raw/FreeCAD/FreeCAD/main/README.md")
    _reply = _nam.get(QtNetwork.QNetworkRequest(_url))
    _loop = QtCore.QEventLoop()
    _reply.finished.connect(_loop.quit)
    QtCore.QTimer.singleShot(30000, _loop.quit)      # never hang the gate
    _loop.exec()
    _body = bytes(_reply.readAll())
    _s.__stderr__.write("FCNET " + repr({
        "error": int(_reply.error().value) if hasattr(_reply.error(), "value") else int(_reply.error()),
        "bytes": len(_body),
    }) + chr(10))
    _s.__stderr__.flush()
except Exception as _e:
    _s.__stderr__.write("FCNET " + repr({"error": -1, "bytes": 0, "why": repr(_e)}) + chr(10))
    _s.__stderr__.flush()

# Separate try: "open this page" does not depend on QtNetwork, and one failing must
# not hide the other. Reporting a working feature as broken is its own defect.
try:
    from PySide6 import QtCore as _QtCore, QtGui as _QtGui

    _handled = _QtGui.QDesktopServices.openUrl(
        _QtCore.QUrl("https://wiki.freecad.org/Main_Page"))
    _s.__stderr__.write("FCOPEN " + repr({"handled": bool(_handled)}) + chr(10))
    _s.__stderr__.flush()
except Exception as _e2:
    _s.__stderr__.write("FCOPEN " + repr({"handled": False, "why": repr(_e2)}) + chr(10))
    _s.__stderr__.flush()
'''

WORKFLOW_PY = r'''
# The half of the manual pass that is fact rather than judgement. A person still has to
# say whether the app LOOKS right; nobody needs to be in the room to find out whether a
# constrained sketch pads to the right volume or a STEP survives a round trip.
import sys as _s
import FreeCAD as App
import Part
import Sketcher

_res = {}
_doc = App.newDocument('GateQA')

try:
    # A rectangle built from constraints, not coordinates, so the solver is exercised.
    _body = _doc.addObject('PartDesign::Body', 'Body')
    _sk = _doc.addObject('Sketcher::SketchObject', 'Sketch')
    _body.addObject(_sk)
    _v = App.Vector
    _sk.addGeometry(Part.LineSegment(_v(0, 0, 0), _v(40, 0, 0)), False)
    _sk.addGeometry(Part.LineSegment(_v(40, 0, 0), _v(40, 25, 0)), False)
    _sk.addGeometry(Part.LineSegment(_v(40, 25, 0), _v(0, 25, 0)), False)
    _sk.addGeometry(Part.LineSegment(_v(0, 25, 0), _v(0, 0, 0)), False)
    for _i in range(4):
        _sk.addConstraint(Sketcher.Constraint('Coincident', _i, 2, (_i + 1) % 4, 1))
    _sk.addConstraint(Sketcher.Constraint('Horizontal', 0))
    _sk.addConstraint(Sketcher.Constraint('Vertical', 1))
    _sk.addConstraint(Sketcher.Constraint('DistanceX', 0, 1, 0, 2, 40.0))
    _sk.addConstraint(Sketcher.Constraint('DistanceY', 1, 1, 1, 2, 25.0))
    _doc.recompute()
    _pad = _doc.addObject('PartDesign::Pad', 'Pad')
    _body.addObject(_pad)
    _pad.Profile = _sk
    _pad.Length = 10.0
    _doc.recompute()
    _res['padVolume'] = round(_pad.Shape.Volume, 6)
    _res['padValid'] = bool(_pad.Shape.isValid())
    _res['sketchDoF'] = _sk.solve()

    _b = Part.makeBox(10, 10, 10)
    _cut = _b.cut(Part.makeCylinder(3, 20, App.Vector(5, 5, -5)))
    _common = _b.common(Part.makeBox(6, 6, 6, App.Vector(4, 4, 4)))
    _res['cutValid'] = bool(_cut.isValid())
    _res['commonVolume'] = round(_common.Volume, 3)

    _step = '/home/web_user/gate_roundtrip.step'
    _src = Part.makeBox(12, 8, 6)
    _src.exportStep(_step)
    _back = Part.Shape()
    _back.read(_step)
    _res['stepValid'] = bool(_back.isValid())
    _res['stepVolumeMatches'] = abs(_back.Volume - _src.Volume) < 1e-6

    _fcstd = '/home/web_user/gate_doc.FCStd'
    _doc.saveAs(_fcstd)
    _name = _doc.Name
    App.closeDocument(_name)
    _re = App.openDocument(_fcstd)
    _vol = None
    for _o in _re.Objects:
        if _o.TypeId == 'PartDesign::Pad':
            _vol = round(_o.Shape.Volume, 6)
    _res['reloadedPadVolume'] = _vol
except Exception as _e:
    _res['error'] = repr(_e)

_s.__stderr__.write('FCQA ' + repr(_res) + chr(10))
_s.__stderr__.flush()
'''
ADDONS_PY = r'''
# The Addon Manager, driven through its own code rather than around it: import the
# module the workbench uses, ask it for the real catalogue, and require a sane answer.
#
# This is the whole chain in one call -- PySide6.QtNetwork bindings exist, the URL
# rewrite sends the request at this origin's /proxy, the proxy is allowed to reach
# raw.githubusercontent.com, and the bytes come back as parseable JSON. Any link in
# that chain breaking leaves the workbench looking installed and doing nothing.
import sys as _s
import sys
_out = {}
try:
    sys.path.append('/freecad/Mod/AddonManager')
except Exception:
    pass
try:
    import json
    import NetworkManager

    _url = 'https://raw.githubusercontent.com/FreeCAD/Addons/main/Data/Index.json'
    _out['rewritten'] = NetworkManager.fcweb_proxy_url(_url)
    # The catalogue is only half of it. On open the workbench also pings
    # addons.freecad.org/status and posts usage stats there. That host was missing
    # from FCWEB_PROXY_HOSTS, so the request was never rewritten, went cross-origin,
    # and COEP:require-corp dropped it -- reported to the user as 'got HTTP status
    # code 0' / 'No data received', followed by a modal raised from the network
    # callback, which is not a promising stack and killed the page with a
    # SuspendError. Reported 2026-09-03 from the dev origin.
    _out['status_rewritten'] = NetworkManager.fcweb_proxy_url(
        'https://addons.freecad.org/status')

    NetworkManager.InitializeNetworkManager()

    # submit_unmonitored_get + the completed signal, NOT blocking_get. The workbench uses
    # a worker thread for the blocking calls, and NetworkManager's own docstring is blunt
    # about why: "Do not use on the main GUI thread, it will prevent any event processing
    # while it blocks."
    #
    # This probe used to call blocking_get from the main thread, which is precisely that.
    # It froze the browser's event loop, so the page stopped answering page.evaluate, and
    # the gate hung -- 65 minutes in CI, past its own budget, because the code that checks
    # the budget was waiting on the frozen page. The test was doing the forbidden thing and
    # reporting it as a product failure.
    #
    # Nothing here waits. The signal writes the result, and the gate polls the log ring
    # for it like every other scenario.
    def _done(index, code, data):
        try:
            _txt = bytes(data).decode('utf-8') if data is not None else ''
            _out['httpCode'] = code
            _out['bytes'] = len(_txt)
            _parsed = json.loads(_txt) if _txt else {}
            _out['addons'] = len(_parsed) if isinstance(_parsed, (dict, list)) else -1
        except Exception as _e2:
            _out['error'] = repr(_e2)
        _s.__stderr__.write('FCADDONS ' + repr(_out) + chr(10))
        _s.__stderr__.flush()

    NetworkManager.AM_NETWORK_MANAGER.completed.connect(_done)
    _out['index'] = NetworkManager.AM_NETWORK_MANAGER.submit_unmonitored_get(_url)
except Exception as _e:
    _out['error'] = repr(_e)
    _s.__stderr__.write('FCADDONS ' + repr(_out) + chr(10))
    _s.__stderr__.flush()
'''
RESOURCES_JS = r"""(() => {
  const out = {};
  for (const r of performance.getEntriesByType('resource')) {
    const m = /(FreeCAD\.(?:js|wasm|data\.gz))/.exec(r.name);
    if (m) out[m[1]] = r.encodedBodySize || r.decodedBodySize || r.transferSize || 0;
  }
  return JSON.stringify(out);
})()"""

WASM_SIZE_JS = r"""(() => {
  const e = performance.getEntriesByType('resource')
    .filter(r => /FreeCAD\.wasm/.test(r.name)).pop();
  if (!e) return 0;
  return e.encodedBodySize || e.decodedBodySize || e.transferSize || 0;
})()"""

COUNT_DOCS_PY = r'''
import FreeCAD as App, sys as _s
_names = list(App.listDocuments().keys())
_vol = -1.0
for _n in _names:
    for _o in App.getDocument(_n).Objects:
        if getattr(_o, "TypeId", "") == "Part::Box":
            _vol = _o.Shape.Volume
_s.__stderr__.write("FCDOCS " + repr({"docs": _names, "boxVolume": _vol}) + "\n")
_s.__stderr__.flush()
'''

# Any of these in the output means the engine died, whatever else it printed.
FATAL = re.compile(
    r'Fatal Python error|Aborted\(\)|RuntimeError: unreachable|null function|'
    r'_PyThreadState_Attach|failed to initialize importlib|memory access out of bounds',
    re.I)

# The shell routes the engine's stdout/stderr into its own DOM log, not the console, so a
# console-only gate would miss both the smoke result AND any Python fatal. Every line does
# pass through window.fcwebLogRing, so define that as a property BEFORE the page loads:
# whatever the shell later assigns gets wrapped rather than replaced. The gate then sees
# every line while testing the SHIPPED page rather than a modified copy.
CAPTURE_JS = """
(() => {
  window.__GATE = [];
  let real = null;
  Object.defineProperty(window, 'fcwebLogRing', {
    configurable: true,
    get() {
      return (line) => {
        try { window.__GATE.push(String(line)); } catch (e) {}
        try { if (real) real(line); } catch (e) {}
      };
    },
    set(fn) { real = fn; },
  });
  // Record window.open: "open this page" is nine call sites in Gui alone (help, the
  // wiki, macro links, project information), and a build where that silently does
  // nothing has nine dead buttons.
  window.__OPENED = [];
  window.open = function (u) {
    try { window.__OPENED.push(String(u)); } catch (e) {}
    return null;
  };
  window.__ERRS = [];
  window.addEventListener('error', (e) => {
    try { window.__ERRS.push(String(e.message) + ' :: ' + ((e.error && e.error.stack) || '')); }
    catch (_) {}
  });
})();
"""

DISPATCH_JS = """(code) => {
  const m = window.fcInstance;
  if (!m || !m._fcweb_run_python) return 'no-bridge';
  const n = new TextEncoder().encode(code).length + 1;
  const q = m._malloc(n);
  m.stringToUTF8(code, q, n);
  (window.fcRunPy || function (mm, pp) { mm._fcweb_run_python(BigInt(pp)); mm._free(pp); })(m, q);
  return 'dispatched';
}"""

AUTOSAVE_DIR_JS = """() => {
  try {
    return window.fcInstance.FS.readdir('/home/web_user/.fcweb-autosave')
             .filter(x => x !== '.' && x !== '..');
  } catch (e) { return null; }
}"""

CHROME_ARGS = [
    # JSPI: the port suspends across JS boundaries (dialogs, long restores). Without it
    # the engine loads and then traps the first time it yields.
    '--enable-features=WebAssemblyJavaScriptPromiseIntegration',
    '--js-flags=--experimental-wasm-jspi',
    # A 182 MB module plus a 145 MB preload needs more than the default headless limits,
    # and an OOM here would read as an engine fault.
    '--disable-dev-shm-usage',
    '--no-sandbox',
]


class Session:
    """One page load, with both output channels and the python bridge."""

    # How long the first successful boot took, in seconds. Later scenarios size their own
    # patience from it rather than from the cold-boot figure on the command line.
    first_ready = None

    # When the gate as a whole must be finished (time.time()), or None for no limit. No
    # single wait may run past it: checking the budget only BETWEEN scenarios bounds how
    # many run, not how long one can sit in a 900-second wait, and a gate that overruns
    # its own budget by six minutes is not bounded, it is optimistic.
    deadline = None

    @staticmethod
    def left(default):
        if Session.deadline is None:
            return default
        return max(5.0, min(float(default), Session.deadline - time.time()))

    # Every call this gate makes into the page has to be able to give up, because the gate
    # asks the PAGE how it is doing. When the application blocks its own event loop --
    # which the Addon Manager's catalogue fetch does -- page.evaluate never returns, and
    # the gate hangs on the very call it would use to notice. Run 32946598073 sat for 65
    # minutes that way, past its own 40-minute budget, on a healthy box: the budget could
    # not fire because the code that checks it was itself blocked.
    #
    # A frozen page is a product failure, and it must read as one instead of as a stuck CI
    # job. 30 s is far longer than any healthy evaluate here (they are sub-second).
    PAGE_CALL_TIMEOUT_MS = 30_000

    def __init__(self, ctx, url, timeout):
        self.console = []
        self.page = ctx.new_page()
        self.page.set_default_timeout(self.PAGE_CALL_TIMEOUT_MS)
        self.page.add_init_script(CAPTURE_JS)
        self.page.on('console', lambda m: self.console.append('%s %s' % (m.type, m.text)))
        self.page.on('pageerror', lambda e: self.console.append('pageerror %s' % e))
        self.url = url
        self.timeout = timeout
        self.elapsed = None
        self.ready = False

    def lines(self):
        try:
            return self.console + self.page.evaluate('window.__GATE || []')
        except Exception:
            return self.console

    def errors(self):
        try:
            return self.page.evaluate('window.__ERRS || []')
        except Exception:
            return []

    def fatals(self):
        return [c for c in self.lines() if FATAL.search(c)]

    def load(self):
        # --timeout is sized for a COLD first boot (the engine is ~250 MB). Applying it
        # unchanged to all eleven scenarios makes the worst case eleven times fifteen
        # minutes, which is not a gate, it is a hostage: one scenario that never reaches
        # Ready without crashing can hold CI for hours and say nothing until the end.
        # Once one boot has worked, a later one has no business taking six times longer.
        budget = self.timeout
        if Session.first_ready is not None:
            budget = max(120.0, min(float(self.timeout), 6.0 * Session.first_ready))
        budget = Session.left(budget)
        t0 = time.time()
        self.page.goto(self.url, timeout=120_000)
        while time.time() - t0 < budget:
            if self.fatals():
                break
            try:
                if self.page.evaluate('!!window.__fcAppReady'):
                    self.ready = True
                    break
            except Exception:
                pass            # navigation/teardown races are not verdicts
            time.sleep(2)
        self.elapsed = time.time() - t0
        if self.ready and Session.first_ready is None:
            Session.first_ready = self.elapsed
        return self.ready

    def phase(self):
        """Whatever the overlay last said -- 'never reached Ready' alone just sends the
        next person hunting."""
        try:
            return self.page.evaluate(
                """() => {
                     const s = document.getElementById('ld-status');
                     const d = document.getElementById('ld-detail');
                     return (s ? s.textContent : '?') + ' / ' + (d ? d.textContent : '');
                   }""").strip()[:160]
        except Exception:
            return 'unknown'

    def run_python(self, code):
        return self.page.evaluate(DISPATCH_JS, code)

    def trapped(self):
        """Did a python call reject? The shell records every rejection in __fcPyErrors.

        A wasm trap is not an exception: Python never unwinds, the marker never arrives,
        and from the page nothing happens at all. Without this a trapped engine costs the
        full wait -- fifteen minutes of CI to learn something the shell knew at once.
        """
        try:
            return [str(e) for e in (self.page.evaluate('window.__fcPyErrors || []') or [])]
        except Exception:
            return []

    def wait_for(self, marker, seconds):
        deadline = time.time() + Session.left(seconds)
        while time.time() < deadline:
            for c in self.lines():
                m = re.search(re.escape(marker) + r' (\{.*\})', c)
                if m:
                    # The probes emit repr(dict), so parse it as a Python literal. JSON
                    # cannot: Python writes True, not true, and a dialog result is mostly
                    # booleans.
                    return ast.literal_eval(m.group(1))
                if marker in c:
                    return True
            trap = self.trapped()
            if trap:
                print('==> the engine trapped while waiting for %s: %s' % (marker, trap[0]))
                return None
            time.sleep(2)
        return None


# What is the heap ceiling?
#
# THREE VERSIONS OF THIS HAVE BEEN WRONG, so the reasoning is written down in full.
#
#   1. `!!(Module.wasmMemory && Module.wasmMemory.grow)` -- Memory.prototype.grow exists on
#      EVERY WebAssembly.Memory, and under -pthread emscripten keeps wasmMemory in the
#      loader's closure and never hangs it off Module. False for a growable build and false
#      for a fixed one: an expression that cannot distinguish the two states it names.
#   2. Allocate until the heap moves. On a FIXED heap that is a malloc storm running until
#      allocation fails -- ten minutes against the 2 GB build before it was killed, and
#      hostile to a shared machine.
#   3. Ask the backing SharedArrayBuffer via `.growable`. Chrome reports false on a wasm
#      memory's buffer whether or not the Memory can grow, so this reported
#      "FIXED (buffer is not growable)" against a build whose loader declares a 4 GB
#      maximum and carries 843 GROWABLE_HEAP_*() accessors.
#
# What actually determines the ceiling is one number in the emitted loader:
#
#     wasmMemory = new WebAssembly.Memory({initial: INITIAL_MEMORY/65536,
#                                          maximum: 65536, shared: true})
#
# 65536 pages x 64 KB = 4 GB. So read it. This is a STATIC fact about the artifact rather
# than a live test of the running heap, and it is labelled that way in the output -- but it
# is the ceiling itself, not a proxy for it, which is more than the previous three managed.
#
# If a Memory object is reachable, grow(1) is tried as a live confirmation. It costs one
# 64 KB page and is harmless.
GROWTH_JS = r"""(async () => {
  const m = window.fcInstance;
  const out = {};
  if (!m) { out.error = 'no module'; return JSON.stringify(out); }
  out.currentMB = m.HEAPU8 ? Math.round(m.HEAPU8.length / 1048576) : null;

  // A live test, when the build exposes the Memory at all.
  let mem = null;
  for (const get of [() => m.wasmMemory,
                     () => m.asm && m.asm.memory,
                     () => m.wasmExports && m.wasmExports.memory]) {
    try { const c = get(); if (c && typeof c.grow === 'function') { mem = c; break; } }
    catch (e) { /* keep looking */ }
  }
  if (mem) {
    try {
      const before = mem.buffer.byteLength;
      mem.grow(1);
      out.live = mem.buffer.byteLength > before ? 'GREW by one page' : 'grow() did not move it';
    } catch (e) { out.live = 'FIXED (' + String(e && e.name || e) + ')'; }
  } else {
    out.live = 'no Memory object reachable from the module';
  }

  // The declared ceiling, read out of the loader this page actually loaded.
  try {
    const tag = Array.from(document.querySelectorAll('script[src]'))
      .map(s => s.src).find(u => /FreeCAD\.js/.test(u));
    if (tag) {
      const txt = await (await fetch(tag)).text();      // already in the HTTP cache
      // Emscripten writes the ceiling two different ways, and the difference IS the
      // answer. A FIXED build emits maximum as an expression equal to the initial size:
      //     new WebAssembly.Memory({initial:INITIAL_MEMORY/65536,
      //                             maximum:INITIAL_MEMORY/65536, shared:true})
      // A GROWABLE build emits a literal page count:
      //     new WebAssembly.Memory({initial:INITIAL_MEMORY/65536,
      //                             maximum:65536, shared:true})
      // Both verified against real artifacts -- the 2 GB production build and the 4 GB one.
      const decl = txt.match(/new WebAssembly\.Memory\(\{([^}]*)\}/);
      const im = txt.match(/INITIAL_MEMORY"\]\s*\|\|\s*(\d+)/);
      if (im) { out.initialMB = Math.round(parseInt(im[1], 10) / 1048576); }
      if (decl) {
        const body = decl[1];
        const lit = body.match(/maximum:\s*(\d+)/);
        if (lit) {
          out.ceilingMB = Math.round(parseInt(lit[1], 10) * 65536 / 1048576);
          out.growable = true;
        } else if (/maximum:\s*INITIAL_MEMORY/.test(body)) {
          out.ceilingMB = out.initialMB;      // maximum == initial: it cannot grow
          out.growable = false;
        }
      }
      out.growableAccessors = (txt.match(/GROWABLE_HEAP_/g) || []).length;
    }
  } catch (e) { out.loaderError = String(e).slice(0, 100); }

  out.verdict = (out.ceilingMB === null || out.ceilingMB === undefined)
    ? 'ceiling unknown (could not read the loader)'
    : ((out.growable ? 'GROWABLE to ' : 'FIXED at ') + out.ceilingMB + ' MB'
       + (out.initialMB ? ' (starts at ' + out.initialMB + ' MB)' : '')
       + (out.growableAccessors ? ', ' + out.growableAccessors + ' growable accessors' : ''));
  return JSON.stringify(out);
})"""

ADDONMGR_OPEN_PY = r'''
# Open the Addon Manager the way the Start page does, then wait for its startup sequence
# to finish. Everything is signal-driven, so the result is reported from a timer rather
# than by blocking -- blocking here would starve the very event loop being tested.
import sys as _s
import addonmanager_freecad_interface as fci

# The first-run consent dialog is a real modal waiting for a human click. It is not what
# is under test, and a headless gate has no way to answer it.
fci.Preferences().set("readWarning2022", True)

import FreeCADGui as Gui
try:
    from PySideWrapper import QtCore
except ImportError:
    from PySide6 import QtCore

_out = {}
_state = {"ticks": 0}


def _report():
    _s.__stderr__.write("FCADDONMGR " + repr(_out) + chr(10))
    _s.__stderr__.flush()


def _tick():
    _state["ticks"] += 1
    try:
        import AddonManager
        cmd = getattr(AddonManager, "_fcweb_cmd", None)
        if cmd is not None:
            _out["addons"] = len(cmd.item_model.repos)
            _out["phasesLeft"] = len(cmd.startup_sequence)
            if _out["addons"] >= 100 and not cmd.startup_sequence:
                _timer.stop()
                _report()
                return
    except Exception as _e:
        _out["error"] = repr(_e)
        _timer.stop()
        _report()
        return
    if _state["ticks"] > 150:
        _out["error"] = "the startup sequence never finished"
        _timer.stop()
        _report()


try:
    Gui.runCommand("Std_AddonMgr")
except BaseException as _e:
    _out["error"] = "runCommand failed: " + repr(_e)
    _report()
else:
    _timer = QtCore.QTimer()
    _timer.timeout.connect(_tick)
    _timer.start(1000)
    globals()["_fcam_gate_timer"] = _timer
'''

ADDONMGR_MACRO_PY = r'''
# Install a macro through the Addon Manager. Macros need two round trips to the wiki (the
# page, then the rawcodeurl inside it) and finish with a toolbar-button prompt, so this
# covers ground the theme install does not touch.
import sys as _s
import os
import AddonManager
import addonmanager_freecad_interface as fci
from Addon import Addon
try:
    from PySideWrapper import QtCore
except ImportError:
    from PySide6 import QtCore

_out = {}
_state = {"ticks": 0}


def _report():
    _s.__stderr__.write("FCAMMACRO " + repr(_out) + chr(10))
    _s.__stderr__.flush()


_cmd = AddonManager._fcweb_cmd
_macros = [r for r in _cmd.item_model.repos
           if getattr(r, "repo_type", None) == Addon.Kind.MACRO]
_out["macrosInCatalogue"] = len(_macros)

if not _macros:
    _out["error"] = "the catalogue listed no macros at all"
    _report()
else:
    _target = _macros[0]
    _out["macro"] = _target.name
    _dir = fci.DataPaths().macro_dir
    _before = set(os.listdir(_dir)) if os.path.isdir(_dir) else set()

    def _tick():
        _state["ticks"] += 1
        _now = set(os.listdir(_dir)) if os.path.isdir(_dir) else set()
        _new = sorted(_now - _before)
        if _new:
            _timer.stop()
            _out["newFiles"] = _new
            _out["status"] = str(_target.status())
            _report()
        elif _state["ticks"] > 120:
            _timer.stop()
            _out["error"] = "the macro never appeared in the macro directory"
            _report()

    _cmd.update(_target)
    _timer = QtCore.QTimer()
    _timer.timeout.connect(_tick)
    _timer.start(1000)
    globals()["_fcam_macro_timer"] = _timer
'''


ADDONMGR_HEALTH_PY = r'''
# Catalogue health: are addon READMEs reachable, and did the download stats arrive?
#
# READMEs are sampled across the whole catalogue via the Addon Manager's own
# get_readme_url, so this exercises the real URL shapes (github /raw/, gitlab /-/blob/,
# raw.githubusercontent, the wiki) rather than one hand-picked addon.
#
# A few 404s are EXPECTED and not a failure: some addons point their metadata at a branch
# that no longer exists (CatppuccinFC does). What matters is the rate -- a proxy or header
# regression takes the whole population down at once, which is what this catches.
import sys as _s
import json
import AddonManager
import addonmanager_utilities as utils
from addonmanager_fcweb_async import async_get

_out = {"checked": 0, "ok": 0, "notFound": 0, "failed": 0, "examples": []}
_cmd = AddonManager._fcweb_cmd
_repos = [r for r in _cmd.item_model.repos if getattr(r, "url", None)]

# Spread the sample over the catalogue instead of taking the first N, which would all be
# the same kind of addon from the same host.
_N = 24
_step = max(1, len(_repos) // _N)
_sample = _repos[::_step][:_N]
_state = {"left": len(_sample)}


def _report():
    _s.__stderr__.write("FCAMHEALTH " + repr(_out) + chr(10))
    _s.__stderr__.flush()


def _stats_then_report():
    """The download counts the Addon Manager sorts by. Blocked as mixed content until now."""
    def arrived(ok, data):
        _out["statsOk"] = bool(ok and data)
        _out["statsBytes"] = len(data) if data else 0
        try:
            parsed = json.loads(bytes(data).decode("utf8")) if data else None
            _out["statsEntries"] = len(parsed) if isinstance(parsed, (dict, list)) else -1
        except Exception as _e:
            _out["statsEntries"] = -1
            _out["statsError"] = repr(_e)
        _report()

    import addonmanager_freecad_interface as fci
    # "AddonsStatsURL", not addon_stats_url -- guessing the key would have made this
    # check silently fetch nothing and pass.
    async_get(fci.Preferences().get("AddonsStatsURL"), arrived, timeout_ms=60000)


def _make_cb(name):
    def _cb(ok, data):
        _out["checked"] += 1
        if ok and data:
            _out["ok"] += 1
        else:
            # async_get reports any non-200 as a failure; record a couple by name so a
            # regression is identifiable from the gate output alone.
            _out["notFound"] += 1
            if len(_out["examples"]) < 4:
                _out["examples"].append(name)
        _state["left"] -= 1
        if _state["left"] <= 0:
            _stats_then_report()

    return _cb


if not _sample:
    _out["error"] = "catalogue was empty"
    _report()
else:
    for _r in _sample:
        try:
            _u = utils.get_readme_url(_r)
        except Exception:
            _u = None
        if not _u:
            _state["left"] -= 1
            continue
        async_get(_u, _make_cb(_r.name), timeout_ms=45000)
    if _state["left"] <= 0:
        _stats_then_report()
'''


ADDONMGR_INSTALL_PY = r'''
# Install and then remove a theme through the Addon Manager's own slots -- cmd.update is
# exactly what the Install button is wired to, so the dependency GUI and the progress
# dialog are exercised, not bypassed.
import sys as _s
import os
import AddonManager
import addonmanager_freecad_interface as fci
try:
    from PySideWrapper import QtCore
except ImportError:
    from PySide6 import QtCore

_out = {}
_state = {"ticks": 0}


def _report():
    _s.__stderr__.write("FCAMINSTALL " + repr(_out) + chr(10))
    _s.__stderr__.flush()


_cmd = AddonManager._fcweb_cmd
_target = None
for _r in _cmd.item_model.repos:
    if "theme" in (getattr(_r, "name", "") or "").lower():
        _target = _r
        break

if _target is None:
    _out["error"] = "no theme addon in the catalogue"
    _report()
else:
    _out["addon"] = _target.name
    _dir = os.path.join(fci.DataPaths().mod_dir, _target.name)

    def _remove():
        from addonmanager_uninstaller import AddonUninstaller
        _un = AddonUninstaller(_target)
        globals()["_fcam_uninstaller"] = _un

        def _removed():
            _out["removed"] = not os.path.isdir(_dir)
            _report()

        _un.finished.connect(_removed)
        _un.run()

    def _tick():
        _state["ticks"] += 1
        if os.path.isdir(_dir):
            _timer.stop()
            _out["installed"] = len(os.listdir(_dir))
            _remove()
        elif _state["ticks"] > 120:
            _timer.stop()
            _out["error"] = "the addon never appeared in Mod/"
            _report()

    _cmd.update(_target)
    _timer = QtCore.QTimer()
    _timer.timeout.connect(_tick)
    _timer.start(1000)
    globals()["_fcam_install_timer"] = _timer
'''


def scenario_boot(ctx, url, args, fail):
    s = Session(ctx, url, args.timeout)
    if not s.load():
        fail('never reached Ready in %ds (overlay last said: %s)' % (args.timeout, s.phase()))
    else:
        # One decimal, because this number is the 2 GB / 4 GB comparison. Whole
        # seconds on a ~9 s boot is a resolution of 11%, which is the same size as
        # the effect being measured.
        print('==> Ready in %.1fs' % s.elapsed)
    for f in s.fatals():
        fail('engine reported a fatal: %s' % f[:300])
        break

    if s.ready and not s.fatals():
        s.run_python(SMOKE_PY)
        r = s.wait_for('FCGATE', 120)
        if not isinstance(r, dict):
            fail('the Part::Box smoke test produced no result in 120s')
        else:
            print('==> geometry: %s' % r)
            if abs(r['volume'] - 6000.0) > 1e-6:
                fail('box volume is %r, expected 6000.0' % r['volume'])
            if r['verts'] != 8 or r['faces'] != 6:
                fail('box topology is %d verts / %d faces, expected 8/6'
                     % (r['verts'], r['faces']))
            if args.expect_version and r['version'] != args.expect_version:
                fail('App.Version() is %s, expected %s' % (r['version'], args.expect_version))
        # The heap ceiling is a build flag that is easy to lose in a link command and
        # impossible to notice until a user's model dies at 2 GB. Ask the running
        # engine what it actually got.
        try:
            heap = s.page.evaluate(
                "() => { const m = window.fcInstance;"
                " return m && m.HEAPU8 ? Math.round(m.HEAPU8.length / 1048576) : -1; }")
            grows = json.loads(s.page.evaluate(GROWTH_JS) or '{}')
            print('==> heap: %s MB in use, %s' % (heap, grows.get('verdict', 'unknown')))
            print('==> heap: live grow() test -- %s' % grows.get('live', 'not run'))
            if grows.get('error') or grows.get('loaderError'):
                print('==> heap: probe incomplete (%s)'
                      % (grows.get('error') or grows.get('loaderError')))
        except Exception:
            pass
        for f in s.fatals():
            fail('engine reported a fatal while working: %s' % f[:300])
            break
    return s


def scenario_restore(ctx, url, args, fail):
    """Two loads, one profile: the returning-user path a fresh profile cannot reach."""
    s1 = Session(ctx, url, args.timeout)
    if not s1.load():
        fail('restore pass 1: never reached Ready (overlay: %s)' % s1.phase())
        return s1
    s1.run_python(MAKE_DOC_PY)
    if not s1.wait_for('FCMADE', 120):
        fail('restore pass 1: the document was never saved')
        return s1

    # Autosave has to install, write a copy, and IDBFS has to persist it. Wait on each
    # step rather than sleeping and hoping -- a test that guesses proves nothing.
    if not s1.wait_for('[autosave] observer installed', 120):
        fail('autosave never installed, so nothing would be restored '
             '(this is how ?no3d was caught disabling it)')
        return s1
    # Wait for THIS document, not for any file. Running after the boot scenario, the
    # autosave directory already holds BootGate.FCStd -- so 'is it non-empty' was true
    # immediately and the reload happened before RestoreProbe had been written. The
    # scenario then reported no documents restored and looked like a product bug.
    listing = None
    deadline = time.time() + 90
    while time.time() < deadline:
        listing = s1.page.evaluate(AUTOSAVE_DIR_JS) or []
        if any('RestoreProbe' in str(f) for f in listing):
            break
        time.sleep(2)
    if not listing:
        fail('autosave installed but wrote nothing to .fcweb-autosave in 90s')
        return s1
    print('==> autosaved: %s' % listing)

    # Force the persist and WAIT for it, rather than sleeping past the 15 s backstop
    # and hoping. The sleep passed locally and failed in CI, which is the signature of
    # a test that depends on load rather than on the thing it claims to check.
    persisted = s1.page.evaluate(
        """() => new Promise((resolve) => {
             try {
               window.fcInstance.FS.syncfs(false, (err) => resolve(err ? String(err) : 'ok'));
             } catch (e) { resolve('throw: ' + e); }
           })""")
    if persisted != 'ok':
        fail('IDBFS refused to persist the autosave (%s) -- work would not survive a reload' % persisted)
    s1.page.close()

    s2 = Session(ctx, url, args.timeout)
    if not s2.load():
        fail('restore pass 2: never reached Ready (overlay: %s)' % s2.phase())
        return s2
    if not s2.wait_for('restored', 120):
        fail('pass 2 did not report restoring the previous session -- a returning user '
             'would find their work gone')
    # ASK AGAIN UNTIL IT ANSWERS, rather than once at the earliest possible moment.
    #
    # "restored" is logged by the shell when it hands the autosaved files back to the
    # engine. Opening them is asynchronous and happens AFTER that line. So the old
    # single-shot query raced the restore it was checking, and on 2026-08-27 (run
    # 33079363822) it lost: the page logged "restored 1 document(s) from your last
    # session", the very next query returned docs=[], and the gate blocked a release
    # over a document that was seconds from being there. It had passed on the two
    # previous links, which is the signature of a race, not a product bug.
    #
    # The assertion is unchanged in substance -- a returning user's work must come back --
    # only the deadline is now explicit instead of accidental. A document that never
    # arrives still fails, and takes 90s to do it.
    #
    # Each attempt gets its OWN marker because wait_for() rescans the whole log from the
    # start and returns the FIRST match: reusing 'FCDOCS' would hand back the first,
    # empty answer forever no matter how many times the probe was re-run.
    r = None
    deadline = time.time() + 90
    attempt = 0
    while time.time() < deadline:
        attempt += 1
        tag = 'FCDOCS%d' % attempt
        s2.run_python(COUNT_DOCS_PY.replace('FCDOCS', tag))
        r = s2.wait_for(tag, 20)
        if isinstance(r, dict) and r.get('docs'):
            break
        time.sleep(3)
    if attempt > 1:
        print('==> restore: the document list took %d attempt(s) to populate' % attempt)
    if not isinstance(r, dict):
        fail('could not read the restored document list')
    else:
        print('==> restored: %s' % r)
        if not r['docs']:
            fail('no documents came back after the reload')
        if abs(r['boxVolume'] - 480.0) > 1e-6:
            fail('the restored box has volume %r, expected 480.0 (12x8x5) -- the document '
                 'came back but its geometry did not survive' % r['boxVolume'])
    for f in s2.fatals():
        fail('restore path reported a fatal: %s' % f[:300])
        break
    return s2


def scenario_dialog(ctx, url, args, fail):
    """A modal has to open, take input, and give the value back."""
    s = Session(ctx, url, args.timeout)
    if not s.load():
        fail('dialog scenario: never reached Ready (overlay: %s)' % s.phase())
        return s
    s.run_python(DIALOG_PY)
    r = s.wait_for('FCDIALOG', 120)
    if not isinstance(r, dict):
        fail('QInputDialog never returned -- a blocking dialog that does not come back '
             'is worse than one that cancels')
    elif not r.get('ok'):
        fail('QInputDialog reported cancelled (%s) -- every prompt-driven command is '
             'dead' % r.get('why', 'no reason given'))
    elif r.get('value') != 'typed-by-gate':
        fail('QInputDialog returned %r, not what was typed' % r.get('value'))
    else:
        print('==> dialog: value came back intact')
    return s


def scenario_imports(ctx, url, args, fail):
    """Half-shipped packages: C extensions linked in, Python package missing."""
    s = Session(ctx, url, args.timeout)
    if not s.load():
        fail('imports scenario: never reached Ready (overlay: %s)' % s.phase())
        return s
    s.run_python(IMPORTS_PY)
    r = s.wait_for('FCIMPORTS', 120)
    if not isinstance(r, dict):
        fail('the import probe produced no result')
        return s
    print('==> imports: %s' % r)
    broken = sorted(k for k, v in r.items() if v != 'ok')
    if broken:
        fail('these cannot be imported: %s -- their C extensions are linked into the '
             'binary but the Python package is not on the filesystem, so the workbenches '
             'that need them (FEM, Draft, BIM, Plot) are dead' % ', '.join(broken))
    return s


def scenario_network(ctx, url, args, fail):
    """Reaching the web at all -- the thing COEP takes away and the proxy gives back."""
    s = Session(ctx, url, args.timeout)
    if not s.load():
        fail('network scenario: never reached Ready (overlay: %s)' % s.phase())
        return s
    s.run_python(NETWORK_PY)
    r = s.wait_for('FCNET', 120)
    if not isinstance(r, dict):
        fail('the network probe produced no result -- Qt never came back from the request')
    elif r.get('error') or r.get('bytes', 0) <= 0:
        fail('the app could not fetch through the proxy (QNetworkReply error %s, %s bytes%s) '
             '-- with this broken the Addon Manager and every documentation link are dead'
             % (r.get('error'), r.get('bytes'), ', ' + r['why'] if r.get('why') else ''))
    else:
        print('==> network: fetched %d bytes through the proxy with Qt' % r['bytes'])

    # "Open this page" has to reach the browser, not merely return true.
    o = s.wait_for('FCOPEN', 30)
    opened = []
    try:
        opened = s.page.evaluate('window.__OPENED || []')
    except Exception:
        pass
    if not isinstance(o, dict) or not o.get('handled'):
        fail('QDesktopServices.openUrl did not handle the URL -- every help, wiki '
             'and macro link in the GUI is a dead button')
    elif not any('wiki.freecad.org' in u for u in opened):
        fail('openUrl returned true but the browser was never asked to open '
             'anything (window.open saw %r)' % (opened,))
    else:
        print('==> links: openUrl reached the browser (%s)' % opened[-1])
    return s


def scenario_workflow(ctx, url, args, fail):
    """Real modelling: a constrained sketch, a pad, booleans, STEP, save and reopen."""
    s = Session(ctx, url, args.timeout)
    if not s.load():
        fail('workflow scenario: never reached Ready (overlay: %s)' % s.phase())
        return s
    s.run_python(WORKFLOW_PY)
    r = s.wait_for('FCQA', 180)
    if not isinstance(r, dict):
        fail('the modelling workflow produced no result')
        return s
    print('==> workflow: %s' % r)
    if r.get('error'):
        fail('the modelling workflow raised %s' % r['error'])
        return s
    if r.get('sketchDoF') != 0:
        fail('the sketch did not solve to zero degrees of freedom (got %r) -- the constraint solver is the heart of parametric modelling' % r.get('sketchDoF'))
    if not r.get('padValid') or abs(r.get('padVolume', 0) - 10000.0) > 1e-6:
        fail('the pad is %r with volume %r, expected a valid solid of 10000.0'
             % (r.get('padValid'), r.get('padVolume')))
    if not r.get('cutValid') or abs(r.get('commonVolume', 0) - 216.0) > 1e-3:
        fail('booleans are wrong: cut valid=%r, common volume=%r (expected 216.0)'
             % (r.get('cutValid'), r.get('commonVolume')))
    if not r.get('stepValid') or not r.get('stepVolumeMatches'):
        fail('a STEP round trip did not come back intact -- interchange is how work leaves this app')
    if abs((r.get('reloadedPadVolume') or 0) - 10000.0) > 1e-6:
        fail('the document reopened with pad volume %r, not 10000.0 -- saved work is not coming back the same' % r.get('reloadedPadVolume'))
    return s

def scenario_addons(ctx, url, args, fail):
    """The Addon Manager fetching the real catalogue through the proxy."""
    s = Session(ctx, url, args.timeout)
    if not s.load():
        fail('addons scenario: never reached Ready (overlay: %s)' % s.phase())
        return s
    s.run_python(ADDONS_PY)
    r = s.wait_for('FCADDONS', 180)
    if not isinstance(r, dict):
        fail('the addon probe produced no result')
        return s
    print('==> addons: %s' % r)
    if r.get('error'):
        fail('the Addon Manager could not reach its catalogue: %s -- the workbench would be installed and useless' % r['error'])
    elif not str(r.get('rewritten', '')).startswith('/proxy/raw/'):
        fail('the catalogue URL was not rewritten through the proxy (got %r), so it would be refused by COEP' % r.get('rewritten'))
    elif not str(r.get('status_rewritten', '')).startswith('/proxy/addons/'):
        fail('addons.freecad.org is not rewritten onto the proxy (got %r) -- the Addon Manager pings it on open, COEP refuses it cross-origin, and the modal it raises from the network callback takes the page down' % r.get('status_rewritten'))
    elif r.get('bytes', 0) < 1000 or r.get('addons', 0) < 10:
        fail('the catalogue came back as %r bytes / %r entries, which is not a real index' % (r.get('bytes'), r.get('addons')))
    return s

def scenario_fem(ctx, url, args, fail):
    """R1: mesh with gmsh, solve with CalculiX, and check the answer against theory."""
    # The mesher and the solver are separate wasm modules the shell fetches on demand.
    # Where they have to exist depends on what is being gated: a directory on disk, or the
    # origin itself. Asking the filesystem about a deployment is how this crashed with
    # "expected str, bytes or os.PathLike object, not NoneType" the first time it ran
    # against production.
    for f in ('gmsh.js', 'gmsh.wasm', 'ccx.js', 'ccx.wasm'):
        if args.base_url:
            import urllib.request
            probe = '%s/%s' % (args.base_url.rstrip('/'), f)
            try:
                # A ranged GET, not HEAD: this origin answers HEAD with 403, and a HEAD
                # that fails where GET succeeds would report the mesher missing when the
                # browser can fetch it perfectly well.
                # ... and a real User-Agent. The origin sits behind Cloudflare, which
                # answers Python-urllib's default agent with 403 while curl and the
                # browser get 200. Probing with an agent nobody else uses measures the
                # edge's opinion of the prober, not whether the file is served.
                req = urllib.request.Request(probe, headers={
                    'Range': 'bytes=0-0',
                    'User-Agent': 'Mozilla/5.0 (freecad-web boot-gate)',
                })
                with urllib.request.urlopen(req, timeout=30) as r:
                    ok = r.status in (200, 206) and len(r.read(1)) == 1
            except Exception as e:
                ok = False
                probe += ' (%s)' % e
            if not ok:
                fail('fem scenario: %s is not served by that origin, so the mesher and '
                     'solver cannot load' % probe)
                return Session(ctx, url, args.timeout)
        elif not os.path.exists(os.path.join(args.directory, f)):
            fail('fem scenario: %s is not in the serve tree, so the mesher and solver '
                 'cannot load. Fetch them alongside the engine rather than skipping the '
                 'scenario -- a gate that quietly does nothing is worse than no gate.' % f)
            return Session(ctx, url, args.timeout)
    s = Session(ctx, url, args.timeout)
    if not s.load():
        fail('fem scenario: never reached Ready (overlay: %s)' % s.phase())
        return s
    s.run_python(FEM_PY)
    r = s.wait_for('FCFEM', 600)
    if not isinstance(r, dict):
        fail('the FEM probe produced no result')
        return s
    print('==> fem: %s' % r)
    if r.get('error'):
        fail('FEM failed: %s (%s)' % (r['error'], r.get('where', '')))
        return s
    if not r.get('nodes'):
        fail('gmsh produced no mesh')
    ratio = r.get('ratio', 0)
    if not 0.95 <= ratio <= 1.05:
        fail('the solve came out at %.3f of the closed-form answer (%s mm solved against '
             '%s mm for %s N over 100 mm of 20x20 steel). Merely non-zero is what the '
             'zero-matrix threading bug produced.'
             % (ratio, r.get('maxDisplacementMm'), r.get('analyticMm'), r.get('loadN')))
    return s


def scenario_examples(ctx, url, args, fail):
    """Open every example the Start page offers. A trap here is invisible from Python."""
    s = Session(ctx, url, args.timeout)
    if not s.load():
        fail('examples scenario: never reached Ready (overlay: %s)' % s.phase())
        return s
    s.run_python(EXAMPLES_PY)
    r = s.wait_for('FCEXAMPLES', 900)
    if not isinstance(r, dict):
        # No summary line means the engine never came back -- a wasm trap, not an
        # exception. Name the file it was on, which the per-file marker recorded.
        tried = [l.split(None, 1)[1].strip() for l in s.lines()
                 if l.startswith('FCEXAMPLE-TRY ')]
        trap = s.trapped()
        fail('the examples probe never finished%s%s. That is a trap, not an exception: '
             'Python cannot catch it and the page shows nothing.'
             % (' -- last file attempted: %s' % tried[-1] if tried else '',
                ' -- the engine reported %s' % trap[0] if trap else ''))
        return s
    print('==> examples: %s' % r)
    broken = sorted(k for k, v in r.items() if not str(v).startswith('ok:'))
    if broken:
        fail('these bundled examples do not open: %s'
             % ', '.join('%s (%s)' % (k, r[k]) for k in broken))
    return s


def scenario_upgrade(ctx, url, args, fail):
    """The returning user whose engine changed underneath them (RELEASE-PLAN V1).

    Boot the PREVIOUS engine, do work, save it, then swap the new engine into the same
    serve directory and reload the same browser profile -- which is exactly what a deploy
    does to someone with the tab open. Two things have to hold: the new engine is the one
    that runs, and the work is still there.

    Nothing had ever tested this. The service worker is a deliberate pass-through so it
    cannot serve a stale engine, but that is an argument, not a measurement, and it says
    nothing about whether a document written by the old build reopens in the new one.
    """
    import glob
    import io

    if not args.upgrade_from:
        fail('upgrade scenario: --upgrade-from was not given, so there is no previous '
             'engine to upgrade from. Point it at the released build (or unpack the live '
             'one); skipping would make this scenario a decoration.')
        return Session(ctx, url, args.timeout)

    served = {}
    for path in glob.glob(os.path.join(args.directory, 'FreeCAD.*')):
        served[os.path.basename(path)] = io.open(path, 'rb').read()
    old = {}
    for name in served:
        src = os.path.join(args.upgrade_from, name)
        if not os.path.exists(src):
            fail('upgrade scenario: %s is not in %s, so the two trees are not comparable'
                 % (name, args.upgrade_from))
            return Session(ctx, url, args.timeout)
        old[name] = io.open(src, 'rb').read()
    if all(old[n] == served[n] for n in served):
        fail('upgrade scenario: the two engines are byte-identical, so this would prove '
             'nothing')
        return Session(ctx, url, args.timeout)

    # infra/Dockerfile stamps every engine URL with the md5 of its content, and refuses to
    # ship if the stamp is not there. Do the same here: an unstamped tree is a shape
    # production never serves, and testing it produces failures nobody can have (the
    # shell's engine cache is keyed on the URL, so without a stamp a returning browser
    # hands the new loader the previous build's wasm -- "ASM_CONSTS[code] is not a
    # function"). Mirror the deploy, then the gate is measuring the deploy.
    import hashlib

    html = os.path.join(args.directory, args.page)
    template = io.open(html, encoding='utf-8', newline='').read()

    def install(blobs):
        for name, data in blobs.items():
            io.open(os.path.join(args.directory, name), 'wb').write(data)
        page = template
        for name, data in blobs.items():
            stamp = hashlib.md5(data).hexdigest()[:12]
            if name.endswith('.data.gz'):
                page = re.sub(r"FreeCAD\.data\.gz(\?v=[A-Za-z0-9]*)?",
                              'FreeCAD.data.gz?v=%s' % stamp, page)
            else:
                base = name.replace('.', r'\.')
                page = re.sub(r"'%s(\?v=[A-Za-z0-9]*)?'" % base,
                              "'%s?v=%s'" % (name, stamp), page)
        io.open(html, 'w', encoding='utf-8', newline='').write(page)

    try:
        install(old)
        s1 = Session(ctx, url, args.timeout)
        if not s1.load():
            fail('upgrade: the PREVIOUS engine did not reach Ready (overlay: %s) -- fix '
                 'that before reading anything into the rest' % s1.phase())
            return s1
        before = s1.page.evaluate(WASM_SIZE_JS)
        s1.run_python(MAKE_DOC_PY)
        if not s1.wait_for('FCMADE', 120):
            fail('upgrade: the previous engine never saved the document')
            return s1
        if not s1.wait_for('[autosave] observer installed', 120):
            fail('upgrade: autosave never installed on the previous engine')
            return s1
        deadline = time.time() + 90
        while time.time() < deadline:
            listing = s1.page.evaluate(AUTOSAVE_DIR_JS) or []
            if any('RestoreProbe' in str(f) for f in listing):
                break
            time.sleep(2)
        else:
            fail('upgrade: the previous engine autosaved nothing in 90s')
            return s1
        persisted = s1.page.evaluate(
            """() => new Promise((resolve) => {
                 try {
                   window.fcInstance.FS.syncfs(false, (err) => resolve(err ? String(err) : 'ok'));
                 } catch (e) { resolve('throw: ' + e); }
               })""")
        if persisted != 'ok':
            fail('upgrade: IDBFS refused to persist on the previous engine (%s)' % persisted)
            return s1
        s1.page.close()
    finally:
        install(served)
        io.open(html, 'w', encoding='utf-8', newline='').write(template)

    s2 = Session(ctx, url, args.timeout)
    if not s2.load():
        # Say WHICH bytes the returning browser got. "It did not start" leaves open
        # whether the swap served a mixed pair or whether something the old engine
        # persisted is what the new one cannot survive, and those are different bugs.
        try:
            got = json.loads(s2.page.evaluate(RESOURCES_JS) or '{}')
        except Exception:
            got = {}
        disk = {}
        for name in ('FreeCAD.js', 'FreeCAD.wasm', 'FreeCAD.data.gz'):
            path = os.path.join(args.directory, name)
            if os.path.exists(path):
                disk[name] = os.path.getsize(path)
        print('==> upgrade: fetched %s' % (got,))
        print('==> upgrade: on disk %s' % (disk,))
        mixed = [n for n in got if n in disk and got[n] and got[n] != disk[n]]
        fail('upgrade: the NEW engine did not reach Ready for a returning user '
             '(overlay: %s)%s. A fresh profile is not the case that breaks.'
             % (s2.phase(),
                ' -- and it fetched a stale %s' % ', '.join(mixed) if mixed
                else ' -- the bytes it fetched match what is being served, so this is '
                     'state the old engine left behind, not a caching problem'))
        return s2
    after = s2.page.evaluate(WASM_SIZE_JS)
    want = os.path.getsize(os.path.join(args.directory, 'FreeCAD.wasm'))
    # window.FCWEB_BUILD is stamped at deploy time and reads "dev" in any local tree, so it
    # cannot tell these two apart. The bytes can: ask the browser how big the engine it
    # actually fetched was, and compare with the one now on disk.
    if after and after != want:
        fail('upgrade: the reload fetched a %d-byte engine while %d bytes are being served '
             '-- the browser kept the old one, so a deploy would not reach anyone with the '
             'tab open' % (after, want))
    else:
        print('==> upgrade: engine %s bytes -> %s bytes (serving %d)'
              % (before or '?', after or '?', want))
    if not s2.wait_for('restored', 180):
        fail('upgrade: nothing was restored, so work saved by the previous engine is gone')
        return s2
    r = s2.wait_for('FCDOCS', 120)
    if not isinstance(r, dict):
        s2.run_python(COUNT_DOCS_PY)
        r = s2.wait_for('FCDOCS', 120)
    if not isinstance(r, dict) or r.get('boxVolume', -1) <= 0:
        fail('upgrade: the restored document has no geometry (%s) -- a name in a list is '
             'not a document' % (r,))
    else:
        print('==> upgrade: restored %s with box volume %s' % (r.get('docs'), r['boxVolume']))
    return s2


def scenario_workbenches(ctx, url, args, fail):
    """Every workbench activates -- MANUAL-QA's "19/19", checked by machine."""
    s = Session(ctx, url, args.timeout)
    if not s.load():
        fail('workbenches scenario: never reached Ready (overlay: %s)' % s.phase())
        return s
    s.run_python(WORKBENCHES_PY)
    r = s.wait_for('FCWB', 300)
    if not isinstance(r, dict):
        fail('the workbench probe produced no result')
        return s
    broken = sorted(k for k, v in r.items() if v != 'ok')
    print('==> workbenches: %d activated, %d failed' % (len(r) - len(broken), len(broken)))
    if broken:
        fail('these workbenches do not activate: %s'
             % ', '.join('%s (%s)' % (k, r[k]) for k in broken))
    return s


def scenario_addoninstall(ctx, url, args, fail):
    """RELEASE-PLAN 2.2: an addon installs from the real index and survives a reload."""
    s1 = Session(ctx, url, args.timeout)
    if not s1.load():
        fail('addoninstall: never reached Ready (overlay: %s)' % s1.phase())
        return s1
    s1.run_python(ADDON_INSTALL_PY)
    r = s1.wait_for('FCADDONINSTALL', 300)
    if not isinstance(r, dict):
        fail('the addon install probe produced no result')
        return s1
    print('==> addon install: %s' % r)
    if r.get('error'):
        fail('installing an addon failed: %s' % r['error'])
        return s1
    if not r.get('pyFiles'):
        fail('the addon unpacked with no Python in it')
        return s1

    persisted = s1.page.evaluate(
        """() => new Promise((resolve) => {
             try {
               window.fcInstance.FS.syncfs(false, (err) => resolve(err ? String(err) : 'ok'));
             } catch (e) { resolve('throw: ' + e); }
           })""")
    if persisted != 'ok':
        fail('IDBFS refused to persist the installed addon (%s)' % persisted)
        return s1
    s1.page.close()

    s2 = Session(ctx, url, args.timeout)
    if not s2.load():
        fail('addoninstall: the second load never reached Ready (overlay: %s)' % s2.phase())
        return s2
    s2.run_python(ADDON_PRESENT_PY)
    r2 = s2.wait_for('FCADDONPRESENT', 180)
    if not isinstance(r2, dict) or not r2.get('pyFiles'):
        fail('the addon did not survive the reload (%s) -- an install that does not '
             'persist is a download' % (r2,))
    else:
        print('==> addon survived the reload: %s (%d .py files)'
              % (r2.get('mods'), r2['pyFiles']))
    return s2


def scenario_addonmgr(ctx, url, args, fail):
    """The Addon Manager workbench itself: open it, list, install, uninstall.

    The `addons` scenario drives NetworkManager directly and `addoninstall` unpacks an
    archive itself, so both kept passing while clicking Addon Manager killed the engine
    outright (CPython aborting in PyGILState_Release). Only the real command exercises the
    workbench's own workers, its modal dialogs and its threading.
    """
    s = Session(ctx, url, args.timeout)
    if not s.load():
        fail('addonmgr: never reached Ready (overlay: %s)' % s.phase())
        return s

    s.run_python(ADDONMGR_OPEN_PY)
    r = s.wait_for('FCADDONMGR', 240)
    if not isinstance(r, dict):
        fail('the Addon Manager never reported: it opened and then stopped responding, '
             'which is what an engine abort looks like from here')
        return s
    print('==> addon manager: %s' % r)
    if r.get('error'):
        fail('the Addon Manager could not start up: %s' % r['error'])
        return s
    if r.get('addons', 0) < 100:
        fail('the catalogue listed %r addons; the real index has hundreds, so the '
             'workbench is open and empty' % r.get('addons'))
        return s
    if r.get('phasesLeft'):
        fail('%r startup phases never ran -- the sequence stalled partway, which leaves '
             'the progress bar up forever' % r.get('phasesLeft'))
        return s

    s.run_python(ADDONMGR_INSTALL_PY)
    ri = s.wait_for('FCAMINSTALL', 240)
    if not isinstance(ri, dict):
        fail('installing through the Addon Manager produced no result')
        return s
    print('==> addon manager install: %s' % ri)
    if ri.get('error'):
        fail('installing through the Addon Manager failed: %s' % ri['error'])
    elif not ri.get('installed'):
        fail('the addon reported installed but its directory is empty')
    elif not ri.get('removed'):
        fail('uninstalling left the addon directory behind')

    s.run_python(ADDONMGR_MACRO_PY)
    rm = s.wait_for('FCAMMACRO', 240)
    if not isinstance(rm, dict):
        fail('installing a macro produced no result -- the macro path ends in a modal '
             'toolbar prompt, and a modal from a callback takes the engine down')
        return s
    print('==> addon manager macro: %s' % rm)
    if rm.get('error'):
        fail('installing a macro through the Addon Manager failed: %s' % rm['error'])
    elif not rm.get('newFiles'):
        fail('the macro installed nothing into the macro directory')

    s.run_python(ADDONMGR_HEALTH_PY)
    rh = s.wait_for('FCAMHEALTH', 300)
    if not isinstance(rh, dict):
        fail('the catalogue health probe produced no result')
        return s
    print('==> addon manager health: %s' % rh)
    if rh.get('error'):
        fail('catalogue health check failed: %s' % rh['error'])
    else:
        checked, good = rh.get('checked', 0), rh.get('ok', 0)
        # A handful of addons genuinely point at dead branches; a proxy regression takes
        # the whole population out at once. Two thirds is well clear of both.
        if checked < 10:
            fail('only %d addon READMEs were checked -- the sample never ran' % checked)
        elif good * 3 < checked * 2:
            fail('only %d of %d addon READMEs loaded (%s) -- that is a proxy or header '
                 'regression, not bad addon metadata'
                 % (good, checked, ', '.join(rh.get('examples', []))))
        if not rh.get('statsOk'):
            fail('addon_stats.json did not arrive -- the download counts and the '
                 '"sort by downloads" ordering are silently empty')
        elif rh.get('statsEntries', 0) < 10:
            fail('addon_stats.json parsed to %r entries, which is not real data'
                 % rh.get('statsEntries'))

    # An abort does not always stop the log arriving, so prove the engine still runs.
    s.run_python('import sys as _s; _s.__stderr__.write("FCAMALIVE {}" + chr(10)); '
                 '_s.__stderr__.flush()')
    if not isinstance(s.wait_for('FCAMALIVE', 60), dict):
        fail('the engine was dead after using the Addon Manager, even though the '
             'catalogue had loaded -- the abort just came later')
    return s


def scenario_render(ctx, url, args, fail):
    """RELEASE-PLAN V6: the viewport draws a shaded solid, not a blank or a silhouette.

    Rendering was unjudgeable for the whole life of this port. It is not: the app issues
    399 GL calls for one box, and the frame can be read -- from Coin's framebuffer, not the
    canvas. This asserts the SHAPE of the result rather than an exact image, because an
    exact image would be a SwiftShader fingerprint and would fail on the first driver
    change. What it catches is the failure that matters: geometry that stops being drawn,
    or shading that collapses to one flat colour.
    """
    if args.base_url:
        base = args.base_url.rstrip('/') + '/?pixelgate=1'
    else:
        base = 'http://127.0.0.1:%d/%s?pixelgate=1' % (args.port, args.page)
    # Say which page this one opens. Every other scenario uses the URL printed at the top
    # of the run, which carries ?no3d -- and a rendering gate that appeared to run against
    # ?no3d would be read, reasonably, as measuring nothing.
    print('==> render: %s' % base)
    s = Session(ctx, base, args.timeout)
    if not s.load():
        fail('render scenario: never reached Ready (overlay: %s)' % s.phase())
        return s
    s.run_python(RENDER_PY)
    if not s.wait_for('FCRENDER', 180):
        fail('render scenario: the box was never built')
        return s
    time.sleep(6)                       # let the view settle and Coin draw the fitted frame
    try:
        frame = json.loads(s.page.evaluate(READ_FRAME_JS) or '{}')
    except Exception as e:
        fail('render scenario: could not read the frame (%s)' % e)
        return s
    if True:
        # DIAGNOSTIC, not an assertion: what does the CANVAS hold after a plain Coin
        # render with no document involved?
        try:
            import os as _os
            rc = json.loads(s.page.evaluate(READ_CANVAS_JS) or '{}')
            print('==> render: CANVAS %dx%d, %d distinct colours, dominant %s at %.1f%%'
                  % (rc.get('w', 0), rc.get('h', 0), rc.get('distinct', 0),
                     rc.get('dominant'), rc.get('dominantPct', 0)))
            _os.makedirs('/tmp/fclogs', exist_ok=True)
            s.page.screenshot(path='/tmp/fclogs/render-canvas.png', full_page=False)
            print('==> render: screenshot %d bytes'
                  % _os.path.getsize('/tmp/fclogs/render-canvas.png'))
        except Exception as e:
            print('==> render: canvas diagnostic failed (%s)' % e)
    if frame.get('error'):
        fail('render scenario: %s' % frame['error'])
        return s

    total = frame.get('total', 0) or 1
    non_bg = frame.get('nonBackground', 0)
    distinct = frame.get('distinct', 0)
    frac = 100.0 * non_bg / total
    print('==> render: %d distinct colours, %.1f%% of the frame is not background, top %s'
          % (distinct, frac, frame.get('top', [])[:3]))

    # A box fitted to the view fills a good fraction of it. Empty (nothing drawn) and
    # full (a clear colour with no scene) are both wrong.
    if frac < 2.0:
        fail('render: only %.1f%% of the frame is non-background -- the viewport drew '
             'nothing, or the scene never reached this buffer' % frac)
    elif frac > 95.0:
        fail('render: %.1f%% of the frame is non-background -- that is a clear colour, '
             'not a scene' % frac)
    # Flat shading, or a silhouette, collapses the colour count. A shaded solid with edges
    # produced 195 distinct colours when this was written.
    if distinct < 8:
        fail('render: only %d distinct colours -- the solid is flat or unlit, which is what '
             'the nine no-op fixed-function GL calls would look like' % distinct)

    # ---- and does near geometry actually HIDE far geometry? -------------------------
    # Everything above is satisfied by a scene with no depth testing at all, which is
    # precisely what shipped on 2026-09-02. See OCCLUDE_PY.
    s.run_python(OCCLUDE_PY)
    if not s.wait_for('FCDEPTH', 180):
        print('==> render: depth sub-check skipped -- the two-box scene never built')
        return s
    time.sleep(6)
    try:
        d = json.loads(s.page.evaluate(READ_FRAME_JS) or '{}')
    except Exception as e:
        print('==> render: depth sub-check could not read the frame (%s)' % e)
        return s
    red, green = d.get('reddish', 0), d.get('greenish', 0)
    print('==> render: depth -- %d reddish px (near box), %d greenish px (far box)'
          % (red, green))
    if green < 1000:
        # The far box is the big one; if it is not on screen the scene is not what this
        # check assumes and the red count would mean nothing either way.
        print('==> render: depth sub-check inconclusive -- the far box did not render')
    elif red < green * 0.05:      # nominal is ~0.25; depth-off drops it to ~0
        fail('render: the near box is hidden by the box BEHIND it (%d reddish px against '
             '%d greenish). Geometry is being drawn without depth testing -- solids render '
             'see-through and interiors show through exteriors.' % (red, green))

    # ---- and do the page's GL registries stay bounded? ------------------------------
    raw_before = s.page.evaluate('() => window.__fcPresentStats ? '
                                 'JSON.stringify(window.__fcPresentStats()) : null')
    if not raw_before:
        print('==> render: leak sub-check skipped -- page predates __fcPresentStats')
        return s
    before = json.loads(raw_before)
    s.run_python(LEAK_PY)
    if not s.wait_for('FCLEAK', 240):
        print('==> render: leak sub-check skipped -- the document cycle never finished')
        return s
    time.sleep(4)
    after = json.loads(s.page.evaluate('() => JSON.stringify(window.__fcPresentStats())'))
    print('==> render: registries before %s after %s (8 document open/close cycles)'
          % (before, after))
    # Six framebuffers per cycle were retained before the delete hooks existed, so eight
    # cycles moved this by ~48. A little slack absorbs what the last view legitimately
    # still holds; anything growing per-cycle blows straight past it.
    if after.get('reg', 0) > before.get('reg', 0) + 8:
        fail('render: the framebuffer registry grew from %d to %d over 8 document '
             'open/close cycles -- entries are not dropped on delete, and present() walks '
             'this map every frame' % (before.get('reg'), after.get('reg')))
    if after.get('upl', 0) > before.get('upl', 0) + 16:
        fail('render: the texture upload list grew from %d to %d over 8 document '
             'open/close cycles -- dead textures are not pruned, and indexOf on this list '
             'is on the upload path' % (before.get('upl'), after.get('upl')))
    return s


def scenario_save(ctx, url, args, fail):
    """Can a user actually leave with their work?

    The File > Save path the app offers has two halves. showSaveFilePicker needs a human
    and is out of reach here. The download-anchor fallback is not: it stages the document
    under /home/web_user/_dl, hands the bytes to the browser as a Blob and clicks an
    <a download>, and a real download event is something Playwright can catch.

    Catching the event is not enough on its own -- a zero-byte file fires one too. So the
    delivered bytes are written back into the application's filesystem and REOPENED, and
    the geometry has to match what went in. 13 x 17 x 19 is 4199, which no accident
    produces.
    """
    import hashlib
    import os as _os
    import zipfile

    s = Session(ctx, url, args.timeout)
    if not s.load():
        fail('save scenario: never reached Ready (overlay: %s)' % s.phase())
        return s

    s.run_python(SAVE_MAKE_PY)
    made = s.wait_for('FCSAVEMAKE', 180)
    if not isinstance(made, dict) or made.get('error') or not made.get('volume'):
        fail('save scenario: the document was not created (%s)' % (made,))
        return s

    s.run_python(SAVE_ACTIVATE_PY)
    act = s.wait_for('FCSAVEACT', 120)
    if not isinstance(act, dict) or act.get('error'):
        fail('save scenario: could not select the document to save (%s)' % (act,))
        return s
    if act.get('active') != 'SaveProbe':
        fail('save scenario: SaveProbe was built but %r is the active document (open: %s). '
             'File > Save saves the active document, so this user would be handed the '
             'wrong file.' % (act.get('active'), act.get('open')))
        return s
    if len(act.get('open') or []) > 1:
        print('==> save: %d documents open, saving %s' % (len(act['open']), act['active']))

    try:
        with s.page.expect_download(timeout=120_000) as info:
            s.page.evaluate('() => window.fcwebDownload && window.fcwebDownload()')
        dl = info.value
    except Exception as e:
        fail('save scenario: File > Save handed the browser nothing (%s). A user who '
             'cannot get a document out of this application has no way to keep their '
             'work.' % e)
        return s

    target = _os.path.join(tempfile.gettempdir(), 'fcweb-save-probe.FCStd')
    try:
        dl.save_as(target)
        blob = io.open(target, 'rb').read()
    except Exception as e:
        fail('save scenario: the download did not complete (%s)' % e)
        return s

    print('==> save: %s, %d bytes, sha256 %s'
          % (dl.suggested_filename, len(blob), hashlib.sha256(blob).hexdigest()[:16]))

    if not blob:
        fail('save scenario: the delivered file is empty')
        return s
    if not zipfile.is_zipfile(io.BytesIO(blob)):
        fail('save scenario: the delivered file is not a zip, so it is not an FCStd')
        return s
    names = zipfile.ZipFile(io.BytesIO(blob)).namelist()
    if 'Document.xml' not in names:
        fail('save scenario: no Document.xml in the delivered file -- %s' % names[:6])
        return s

    # Round trip: push the delivered bytes back in and reopen them.
    s.page.evaluate("""(b64) => {
        const m = window.fcInstance;
        const bin = atob(b64);
        const buf = new Uint8Array(bin.length);
        for (let i = 0; i < bin.length; i++) { buf[i] = bin.charCodeAt(i); }
        m.FS.writeFile('/home/web_user/_readback.FCStd', buf);
        return true;
    }""", base64.b64encode(blob).decode())
    s.run_python(SAVE_REOPEN_PY)
    back = s.wait_for('FCSAVEBACK', 180)
    if not isinstance(back, dict) or back.get('error'):
        fail('save scenario: the delivered file would not reopen (%s)' % (back,))
        return s
    if back.get('volume') != made.get('volume'):
        fail('save scenario: the file came back with volume %s, but %s went in -- the '
             'user would be handed a document that is not theirs'
             % (back.get('volume'), made.get('volume')))
        return s
    print('==> save: reopened from the delivered bytes -- %d object(s), volume %s'
          % (back.get('objects'), back.get('volume')))
    return s


def scenario_storage(ctx, url, args, fail):
    """Will the browser keep the user's documents, and does the app say so when it will not?

    The PWA install grant needs a human: Chrome ties navigator.storage.persist() to
    installation and engagement, and a headless visit is never going to earn it. So this
    does the two things a machine can.

    It RECORDS the durability state -- granted or not, and the quota -- because "we do not
    know" is the answer this project has had until now.

    And it exercises the branch a real first-time user gets. fcwebWarnEvictable is called
    the moment someone saves real work; on a browser that has not granted persistence it
    has to tell them their documents can be cleared, and offer the backup folder. Silence
    there is the failure mode that loses somebody a day of work, and silence is exactly
    what a passing test looks like if nobody checks.
    """
    s = Session(ctx, url, args.timeout)
    if not s.load():
        fail('storage scenario: never reached Ready (overlay: %s)' % s.phase())
        return s

    try:
        state = json.loads(s.page.evaluate(STORAGE_STATE_JS) or '{}')
    except Exception as e:
        fail('storage scenario: could not read the storage state (%s)' % e)
        return s
    print('==> storage: %s' % state)
    if not state.get('hasApi'):
        fail('storage scenario: navigator.storage is absent, so durability cannot even be '
             'asked about')
        return s

    try:
        warn = json.loads(s.page.evaluate(WARN_EVICTABLE_JS) or '{}')
    except Exception as e:
        fail('storage scenario: the evictable warning threw (%s)' % e)
        return s

    if warn.get('error'):
        fail('storage scenario: %s -- the app has no way to tell a user their documents '
             'are evictable' % warn['error'])
        return s

    if state.get('persisted'):
        print('==> storage: persistence is GRANTED here, so the warning is correctly silent')
        return s

    if warn.get('after', 0) <= warn.get('before', 0):
        fail('storage scenario: storage is NOT persisted and the app said nothing. A user '
             'would have no idea the browser can clear their documents -- and this is the '
             'state every first-time visitor is in.')
        return s

    print('==> storage: not persisted, and the app warns -- %r' % warn.get('text', '')[:160])
    if warn.get('buttons'):
        print('==> storage: offered %s' % (warn['buttons'],))
    return s


def scenario_swigbridge(ctx, url, args, fail):
    """Can a Python view provider hand a coin node to C++?

    This is the gate that did not exist when a black viewport shipped. Every other scenario
    builds geometry through C++ view providers, which never touch FreeCAD's SWIG bridge, so
    all thirteen passed against a build whose bridge was completely dead -- and any user
    opening a project with an Assembly or Draft view provider got a black screen and a wall
    of "No SWIG wrapped library loaded".

    It asserts the conversion works, and then reads the display mode back, so a version that
    silently does nothing cannot pass either.
    """
    s = Session(ctx, url, args.timeout)
    if not s.load():
        fail('swigbridge scenario: never reached Ready (overlay: %s)' % s.phase())
        return s

    s.run_python(SWIGBRIDGE_PY)
    r = s.wait_for('FCSWIG', 240)
    if not isinstance(r, dict):
        fail('swigbridge scenario: the probe returned nothing (%s)' % (r,))
        return s
    if r.get('error'):
        fail('swigbridge scenario: %s -- a Python view provider cannot give Coin its scene '
             'graph, so any document carrying one (Assembly, Draft) opens to a BLACK '
             'VIEWPORT. Check that FreeCAD and pivy were built with the same SWIG: '
             'tools/check-swig-runtime.py' % r['error'])
        return s
    if r.get('addDisplayMode') != 'ok':
        fail('swigbridge scenario: addDisplayMode did not report success (%s)' % (r,))
        return s
    print('==> swigbridge: pivy %s, addDisplayMode ok, modes=%s'
          % (r.get('pivy'), r.get('modes')))
    return s


def scenario_project3d(ctx, url, args, fail):
    """Open a real project with the 3D pipeline on, and check the viewport DREW something.

    This is the gate whose absence let three rendering faults reach users on the same day.
    Each of them produced a black viewport; each was invisible to every existing scenario,
    because they all build geometry through C++ view providers that never cross the SWIG
    bridge or the compositor.

    It asserts two things a black frame cannot satisfy: the document's objects came back
    visible (so their Python view providers built a scene graph at all), and the frame
    carries real content rather than one flat colour.

    Like the render scenario it runs against ?pixelgate=1, and like that one it reports a
    SHAPE rather than an exact image -- an exact image would be a driver fingerprint.
    """
    if args.base_url:
        base = args.base_url.rstrip('/') + '/?pixelgate=1'
    else:
        base = 'http://127.0.0.1:%d/%s?pixelgate=1' % (args.port, args.page)
    print('==> project3d: %s' % base)
    s = Session(ctx, base, args.timeout)
    if not s.load():
        fail('project3d scenario: never reached Ready (overlay: %s)' % s.phase())
        return s

    # BEFORE the project opens. If this one has a painted window in it and the after-shot
    # is black, the failure belongs to whatever opening a document does -- not to boot,
    # not to the compositor in general.
    try:
        os.makedirs('/tmp/fclogs', exist_ok=True)
        s.page.evaluate("() => { const l = document.getElementById('load');"
                        "        if (l) l.style.display = 'none'; }")
        time.sleep(2)
        s.page.screenshot(path='/tmp/fclogs/project3d-before.png', full_page=False)
        print('==> project3d: BEFORE screenshot %d bytes'
              % os.path.getsize('/tmp/fclogs/project3d-before.png'))
    except Exception as e:
        print('==> project3d: before-screenshot failed (%s)' % e)

    if os.environ.get('FCWEB_COUNT_DRAWS'):
        try:
            print('==> project3d: draw counter %s'
                  % s.page.evaluate(DRAW_COUNT_INSTALL_JS))
        except Exception as e:
            print('==> project3d: draw counter install failed (%s)' % e)

    s.run_python(PROJECT3D_PY)
    r = s.wait_for('FCPROJ3D', 300)
    if not isinstance(r, dict) or r.get('error'):
        fail('project3d scenario: the project would not open (%s)' % (r,))
        return s
    print('==> project3d: %s -- %s objects, %s visible'
          % (r.get('file'), r.get('objects'), r.get('visible')))
    if not r.get('visible'):
        fail('project3d scenario: %s opened with %s objects and NONE visible -- their view '
             'providers did not build a scene graph, which is what a dead SWIG bridge looks '
             'like from here' % (r.get('file'), r.get('objects')))
        return s

    time.sleep(6)                      # let Coin draw the fitted frame
    try:
        frame = json.loads(s.page.evaluate(READ_FRAME_JS) or '{}')
    except Exception as e:
        fail('project3d scenario: could not read the frame (%s)' % e)
        return s
    if frame.get('error'):
        fail('project3d scenario: %s' % frame['error'])
        return s

    print('==> project3d: offscreen buffer has %d distinct colours, %.1f%% non-background'
          % (frame.get('distinct', 0),
             100.0 * frame.get('nonBackground', 0) / (frame.get('total', 0) or 1)))

    # THE ONE THAT MATTERS. The frame above is Coin's private FBO -- it can be perfect while
    # the user sees black, because the composite from that FBO to the canvas is a separate
    # step and that is the step that broke. Read the default framebuffer.
    try:
        canvas = json.loads(s.page.evaluate(READ_CANVAS_JS) or '{}')
    except Exception as e:
        fail('project3d scenario: could not read the canvas (%s)' % e)
        return s
    if canvas.get('error'):
        fail('project3d scenario: canvas read failed -- %s' % canvas['error'])
        return s

    print('==> project3d: CANVAS %dx%d, %d distinct colours, dominant %s at %.1f%%'
          % (canvas.get('w', 0), canvas.get('h', 0), canvas.get('distinct', 0),
             canvas.get('dominant'), canvas.get('dominantPct', 0)))

    # GROUND TRUTH. Everything above reads GL state; this reads the screen.
    #
    # A PNG of a single flat colour compresses to almost nothing, so the byte count alone
    # separates "black rectangle" from "a drawing" without needing an image library in the
    # container. The file is kept either way -- on a failure it is the single most useful
    # artefact this gate can hand a human, and it is a few KB.
    # Explain the frame, do not just record it.
    try:
        st = json.loads(s.page.evaluate(DOM_STACK_JS) or '{}')
        print('==> project3d: nativeComposite=%s coinFbo=%s'
              % (st.get('nativeComposite'), st.get('coinFbo')))
        print('==> project3d: at centre of viewport: %s' % (st.get('atCentre'),))
        print('==> project3d: shadow roots: %s' % (st.get('shadowRoots'),))
        print('==> project3d: crossOriginIsolated=%s cores=%s'
              % (st.get('crossOriginIsolated'), st.get('hardwareConcurrency')))
        print('==> project3d: %s' % st.get('pixelGlSameCanvas'))
        for c in st.get('canvases', []):
            print('==> project3d: canvas %s' % c)
        for b in st.get('big', [])[:8]:
            print('==> project3d: covers %s' % b)
    except Exception as e:
        print('==> project3d: DOM probe failed (%s)' % e)

    # EXPERIMENT: hand presentation back to the JS overlay and look again.
    if os.environ.get('FCWEB_TRY_OVERLAY'):
        try:
            print('==> project3d: --- handing presentation to the JS overlay ---')
            s.page.evaluate("() => { window.__fcNativeComposite = 0; }")
            # Force Coin to draw a fresh frame so the overlay has something to capture.
            s.run_python(
                'import FreeCADGui as Gui, sys as _s' + chr(10)
                + 'try:' + chr(10)
                + '    Gui.SendMsgToActiveView("ViewFit")' + chr(10)
                + '    Gui.activeDocument().activeView().redraw()' + chr(10)
                + 'except Exception as e:' + chr(10)
                + '    pass' + chr(10)
                + '_s.__stderr__.write("FCOVL {}" + chr(10))' + chr(10)
                + '_s.__stderr__.flush()' + chr(10))
            s.wait_for('FCOVL', 60)
            time.sleep(6)
            c2 = json.loads(s.page.evaluate(READ_CANVAS_JS) or '{}')
            print('==> project3d: OVERLAY CANVAS %dx%d, %d distinct colours, dominant %s at %.1f%%'
                  % (c2.get('w', 0), c2.get('h', 0), c2.get('distinct', 0),
                     c2.get('dominant'), c2.get('dominantPct', 0)))
            s.page.screenshot(path='/tmp/fclogs/project3d-overlay.png', full_page=False)
            print('==> project3d: OVERLAY screenshot %d bytes'
                  % os.path.getsize('/tmp/fclogs/project3d-overlay.png'))
        except Exception as e:
            print('==> project3d: overlay experiment failed (%s)' % e)

    # Force a repaint and look again.
    if os.environ.get('FCWEB_TRY_REPAINT'):
        try:
            os.makedirs('/tmp/fclogs', exist_ok=True)
            print('==> project3d: --- forcing a resize to make Qt repaint ---')
            s.page.set_viewport_size({'width': 1180, 'height': 700})
            time.sleep(4)
            s.page.set_viewport_size({'width': 1280, 'height': 720})
            time.sleep(6)
            c3 = json.loads(s.page.evaluate(READ_CANVAS_JS) or '{}')
            print('==> project3d: AFTER-RESIZE CANVAS %dx%d, %d distinct colours, '
                  'dominant %s at %.1f%%'
                  % (c3.get('w', 0), c3.get('h', 0), c3.get('distinct', 0),
                     c3.get('dominant'), c3.get('dominantPct', 0)))
            s.page.screenshot(path='/tmp/fclogs/project3d-resized.png', full_page=False)
            print('==> project3d: AFTER-RESIZE screenshot %d bytes'
                  % os.path.getsize('/tmp/fclogs/project3d-resized.png'))
        except Exception as e:
            print('==> project3d: repaint experiment failed (%s)' % e)

    # Do the C++ fix's job from JavaScript, on this already-broken build.
    if os.environ.get('FCWEB_TRY_GLRESET'):
        try:
            os.makedirs('/tmp/fclogs', exist_ok=True)
            print('==> project3d: --- resetting GL state from JS ---')
            print('==> project3d: %s' % s.page.evaluate(GL_RESET_JS))
            # Give Qt a reason to repaint now that the context is clean. A resize on its
            # own was already tried and did nothing, so anything that appears here is the
            # reset's doing, not the resize's.
            s.page.set_viewport_size({'width': 1180, 'height': 700})
            time.sleep(4)
            s.page.set_viewport_size({'width': 1280, 'height': 720})
            time.sleep(6)
            c4 = json.loads(s.page.evaluate(READ_CANVAS_JS) or '{}')
            print('==> project3d: AFTER-GLRESET CANVAS %dx%d, %d distinct colours, '
                  'dominant %s at %.1f%%'
                  % (c4.get('w', 0), c4.get('h', 0), c4.get('distinct', 0),
                     c4.get('dominant'), c4.get('dominantPct', 0)))
            s.page.screenshot(path='/tmp/fclogs/project3d-glreset.png', full_page=False)
            print('==> project3d: AFTER-GLRESET screenshot %d bytes'
                  % os.path.getsize('/tmp/fclogs/project3d-glreset.png'))
        except Exception as e:
            print('==> project3d: glreset experiment failed (%s)' % e)

    # WHO IS STILL DRAWING?
    if os.environ.get('FCWEB_COUNT_DRAWS'):
        try:
            d = json.loads(s.page.evaluate(DRAW_COUNT_READ_JS) or '{}')
            print('==> project3d: draws since instrumentation -- '
                  'to framebuffer 0: %s, to Coin FBO: %s, to other FBOs: %s, '
                  'errors after a draw: %s (last other fbo %s)'
                  % (d.get('toZero'), d.get('toCoinFbo'), d.get('toOther'),
                     d.get('errors'), d.get('lastOtherFbo')))
        except Exception as e:
            print('==> project3d: draw counter read failed (%s)' % e)

    shot = None
    try:
        os.makedirs('/tmp/fclogs', exist_ok=True)
        shot = '/tmp/fclogs/project3d.png'
        s.page.screenshot(path=shot, full_page=False)
        size = os.path.getsize(shot)
        print('==> project3d: SCREENSHOT %s, %d bytes' % (shot, size))
        # A 1200x700 PNG of one flat colour lands around 5-10 KB. Anything with real
        # geometry in it is far larger. This is a smell test, not the assertion.
        if size < 20000:
            print('==> project3d: that is small enough to be a flat rectangle')
    except Exception as e:
        print('==> project3d: screenshot failed (%s)' % e)

    if canvas.get('distinct', 0) < 8:
        fail('project3d scenario: the CANVAS has only %d distinct colours after opening %s. '
             'Coin may have rendered fine into its own buffer -- what reaches the user is '
             'blank. Look for "Feedback loop formed between Framebuffer and active Texture".'
             % (canvas.get('distinct', 0), r.get('file')))
    elif canvas.get('dominantIsDark') and canvas.get('dominantPct', 0) > 90:
        fail('project3d scenario: %.1f%% of the CANVAS is the near-black colour %s after '
             'opening %s. This is the black-viewport failure exactly.'
             % (canvas.get('dominantPct'), canvas.get('dominant'), r.get('file')))
    return s


# Every scenario, once. An entry supplies its argparse choice, its dispatch order,
# whether "all" includes it, and the sentence the pass line prints.
#
# Those four things lived in four places until 2026-08-26, and by then they had drifted:
# the pass-line lookup knew eight of the sixteen scenarios, so "--scenario save" created a
# document, saved it, downloaded it, reopened the delivered bytes, checked the geometry
# matched -- and then died with KeyError('save') while looking up its own name. The render
# gate had been exiting non-zero the same way for days, invisible because that CI step is
# continue-on-error. A gate that does all of its work and then fails to say so is worse
# than one that never ran, because the exit code says the build is broken.
#
# in_all is False for render (needs the 3D pipeline, and "all" runs ?no3d) and for upgrade
# (rewrites the serve tree under itself).
SCENARIOS = (
    # name            function                in_all  what a pass actually means
    ('boot',          scenario_boot,          True,
     'starts and does CAD work'),
    ('restore',       scenario_restore,       True,
     'gives work back after a reload'),
    ('dialog',        scenario_dialog,        True,
     'can ask the user a question and use the answer'),
    ('imports',       scenario_imports,       True,
     'can import the Python packages its workbenches need'),
    ('network',       scenario_network,       True,
     'can reach the web through the proxy'),
    ('workflow',      scenario_workflow,      True,
     'can model: constrained sketch, pad, booleans, STEP, save and reopen'),
    ('addons',        scenario_addons,        True,
     'can reach the addon catalogue through the proxy'),
    ('fem',           scenario_fem,           True,
     'solves a cantilever to within 5% of the closed form'),
    ('examples',      scenario_examples,      True,
     'opens the bundled example documents'),
    ('workbenches',   scenario_workbenches,   True,
     'activates every workbench it ships'),
    ('addoninstall',  scenario_addoninstall,  True,
     'installs an addon from the real catalogue and still has it after a reload'),
    ('addonmgr',      scenario_addonmgr,      True,
     'opens the Addon Manager, lists it, installs an addon and a macro, and keeps READMEs and download stats reachable'),
    ('save',          scenario_save,          True,
     'hands the user a real .FCStd whose bytes reopen to the same geometry'),
    ('storage',       scenario_storage,       True,
     'knows whether the browser will keep the documents, and warns when it will not'),
    ('swigbridge',    scenario_swigbridge,    True,
     'lets a Python view provider hand its scene graph to Coin'),
    ('project3d',     scenario_project3d,     False,
     'opens a real project with 3D on and actually draws it'),
    ('render',        scenario_render,        False,
     'draws a shaded solid in the 3D viewport'),
    ('upgrade',       scenario_upgrade,       False,
     'survives an engine upgrade with the documents intact'),
)

# Nothing below may name a scenario this table does not.
assert len({s[0] for s in SCENARIOS}) == len(SCENARIOS), 'duplicate scenario name'
SCENARIO_NAMES = tuple(s[0] for s in SCENARIOS) + ('all',)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('directory', nargs='?', default=None,
                    help='a serve tree to gate. Omit when --base-url is given.')
    ap.add_argument('--base-url', default=None,
                    help='gate a DEPLOYMENT instead of a directory, e.g. '
                         'https://freecad.virtastic.app. Nothing is served locally; the '
                         'scenarios run against whatever that origin is actually '
                         'shipping. This is the only way to answer "what does the live '
                         'site do" without a person clicking through it.')
    ap.add_argument('--port', type=int, default=8795)
    ap.add_argument('--timeout', type=int, default=900, help='seconds to reach Ready')
    ap.add_argument('--expect-version', default=None, help='e.g. 1.1.3')
    ap.add_argument('--page', default='index.html')
    ap.add_argument('--scenario', default='boot', choices=SCENARIO_NAMES)
    ap.add_argument('--browser', default='chromium',
                    choices=('chromium', 'firefox', 'webkit'),
                    help='which engine to run in. Chromium is the only one with JSPI today, so firefox/webkit are how the Asyncify fallback gets tested rather than assumed (RELEASE-PLAN 2.7).')
    ap.add_argument('--upgrade-from', default=None,
                    help='a serve tree holding the PREVIOUS engine. The upgrade scenario boots that one, saves work, swaps this one in and reloads the same profile -- the returning user a fresh profile never tests (V1).')
    ap.add_argument('--budget', type=int, default=2400,
                    help='seconds for the WHOLE gate. Eleven scenarios that each wait out '
                         'their own timeout can hold CI for hours and say nothing until the '
                         'end; when this is spent the gate stops and names the scenario it '
                         'was in.')
    ap.add_argument('--with-3d', action='store_true',
                    help='leave the 3D pipeline on (headless GL proves little; see V6)')
    args = ap.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print('::error::playwright is not installed. pip install playwright && '
              'python -m playwright install chromium', file=sys.stderr)
        return 2

    ran = []            # labels of the scenarios that actually ran, for the pass line
    server = None
    if args.base_url:
        if args.scenario == 'upgrade':
            print('::error::the upgrade scenario rewrites the serve tree, so it cannot run '
                  'against a deployment', file=sys.stderr)
            return 2
    else:
        if not args.directory:
            print('::error::give a serve tree, or --base-url to gate a deployment',
                  file=sys.stderr)
            return 2
        for f in ('FreeCAD.js', 'FreeCAD.wasm'):
            if not os.path.exists(os.path.join(args.directory, f)):
                print('::error::%s is missing from %s' % (f, args.directory), file=sys.stderr)
                return 2

        here = os.path.dirname(os.path.abspath(__file__))
        server = subprocess.Popen(
            [sys.executable, os.path.join(here, 'serve-artifact.py'), args.directory,
             str(args.port)],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        time.sleep(1.5)
        if server.poll() is not None:
            print('::error::the static server exited immediately: %s'
                  % server.stderr.read().decode('utf-8', 'replace'), file=sys.stderr)
            return 2

    failures = []

    def fail(msg):
        failures.append(msg)

    if args.base_url:
        url = '%s/%s' % (args.base_url.rstrip('/'),
                         '' if args.with_3d else '?no3d')
    else:
        url = 'http://127.0.0.1:%d/%s%s' % (args.port, args.page,
                                            '' if args.with_3d else '?no3d')
    profile = tempfile.mkdtemp(prefix='fcgate-profile-')
    try:
        with sync_playwright() as pw:
            # A persistent context throughout: scenario `restore` needs IndexedDB to
            # survive between loads, and `boot` is unaffected by having one.
            engine = getattr(pw, args.browser)
            # The JSPI flags are Chromium's; passing them to another engine is at
            # best ignored and at worst a launch failure.
            launch_args = CHROME_ARGS if args.browser == 'chromium' else []
            kw = {}
            if args.browser == 'firefox':
                # Headless Firefox ships with WebGL2 off, so the app's own capability
                # gate refuses it before downloading anything -- which says something
                # about this container, not about Firefox. A desktop Firefox has WebGL2.
                kw['firefox_user_prefs'] = {
                    'webgl.disabled': False,
                    'webgl.force-enabled': True,
                    'gfx.webrender.all': True,
                    'dom.webgpu.enabled': False,
                }
            ctx = engine.launch_persistent_context(profile, headless=True,
                                                   args=launch_args, **kw)
            print('==> %s (scenario: %s)' % (url, args.scenario))
            # A watchdog that asks the page NOTHING.
            #
            # Everything else here bounds itself by talking to the browser, and that is
            # exactly what fails when the application blocks its own event loop: the
            # Addon Manager's catalogue fetch does not yield, so the page stops answering
            # and every page.evaluate blocks forever. Playwright's default timeout does
            # not cover evaluate, so there is nothing to catch. Run 32946598073 sat 65
            # minutes past a 40-minute budget on a healthy box for this reason -- the code
            # that checks the budget was itself waiting on the frozen page.
            #
            # So: a plain thread, a clock, and os._exit. It cannot be blocked by the page
            # because it never touches it. A frozen application then reads as a failure
            # with the scenario named, which is what it is.
            watchdog_scenario = ['(starting)']

            def watchdog():
                limit = args.budget + 300      # the gate's own budget, plus slack to report
                time.sleep(limit)
                sys.stderr.write(
                    '::error::the gate made no progress for %ds while running %r. The page '
                    'stopped answering -- that is the application blocking its own event '
                    'loop, not a slow test, and no page-level timeout can catch it because '
                    'page.evaluate has none.\n' % (limit, watchdog_scenario[0]))
                sys.stderr.flush()
                os._exit(3)

            threading.Thread(target=watchdog, daemon=True).start()

            gate_started = time.time()
            out_of_time = False
            Session.deadline = gate_started + args.budget

            def over_budget(after):
                spent = time.time() - gate_started
                if spent < args.budget:
                    return False
                fail('the gate ran out of time (%.0fs of %ds) after %s. A scenario that '
                     'cannot finish is a failure, not a wait -- raise --budget only if the '
                     'work genuinely grew.' % (spent, args.budget, after))
                return True
            dump = []

            def run_scenario(name, fn):
                """Run one scenario, harvest its output, and CLOSE its page.

                Every scenario used to be kept open until the end so its log could be
                dumped on failure. Eleven Chromium pages, each holding a ~250 MB engine
                and its heap, is more than the box has: run 32893773921 was OOM-killed
                (exit 137) 48 minutes in, having looked like a hang for most of it. The
                logs are read out here instead, while the page is still alive, and the
                page goes immediately.
                """
                watchdog_scenario[0] = name
                sess = fn(ctx, url, args, fail)
                try:
                    dump.append((sess.lines(), sess.console, sess.errors()))
                except Exception:
                    dump.append(([], [], []))
                try:
                    sess.page.close()
                except Exception:
                    pass        # restore/upgrade/addoninstall close their own first page
                return over_budget(name)

            for _name, _fn, _in_all, _label in SCENARIOS:
                if out_of_time:
                    continue
                if args.scenario == 'all':
                    if not _in_all:
                        continue
                elif args.scenario != _name:
                    continue
                ran.append(_label)
                out_of_time = run_scenario(_name, _fn)
            ctx.close()
    finally:
        if server is not None:
            server.terminate()
        shutil.rmtree(profile, ignore_errors=True)

    if failures:
        for f in failures:
            print('::error::%s' % f)
        for lines, console, errs in dump:
            engine = [c for c in lines if c not in console]
            print('\n--- last 30 lines from the ENGINE ---', file=sys.stderr)
            for c in (engine[-30:] or ['(the engine printed nothing at all)']):
                print(c[:300], file=sys.stderr)
            if errs:
                print('--- page errors ---', file=sys.stderr)
                for e in errs[:5]:
                    print(e[:500], file=sys.stderr)
            print('--- last 15 console lines ---', file=sys.stderr)
            for c in console[-15:]:
                print(c[:300], file=sys.stderr)
        return 1

    # Say what was actually checked, from the same table that ran it. A pass line that
    # claims more than the run covered is how a gate starts being trusted for things it
    # never tested -- and a hand-kept second list is how it stops matching.
    if not ran:
        print('::error::no scenario ran, so there is nothing to pass', file=sys.stderr)
        return 1
    if len(ran) == 1:
        print('==> boot gate passed: the application %s' % ran[0])
    else:
        print('==> boot gate passed, %d scenarios. The application:' % len(ran))
        for _r in ran:
            print('      - %s' % _r)
    return 0


if __name__ == '__main__':
    sys.exit(main())
