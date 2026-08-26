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
      const rec = {
        distinct: Object.keys(cols).length,
        total: total,
        background: bg,
        nonBackground: total - bg,
        top: Object.entries(cols).sort((a, b) => b[1] - a[1]).slice(0, 6),
      };
      if (!best || rec.distinct > best.distinct) best = rec;
    } catch (e) { /* not every framebuffer is readable */ }
  }
  gl.bindFramebuffer(gl.READ_FRAMEBUFFER, prev);
  return JSON.stringify(best || {error: 'no readable framebuffer'});
})()"""

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

    NetworkManager.InitializeNetworkManager()
    _idx = NetworkManager.AM_NETWORK_MANAGER.blocking_get(_url)
    _txt = bytes(_idx).decode('utf-8') if _idx is not None else ''
    _out['bytes'] = len(_txt)
    _data = json.loads(_txt) if _txt else {}
    _out['addons'] = len(_data) if isinstance(_data, (dict, list)) else -1
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
  (window.fcRunPy || function (mm, pp) { mm._fcweb_run_python(pp); mm._free(pp); })(m, q);
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


def scenario_boot(ctx, url, args, fail):
    s = Session(ctx, url, args.timeout)
    if not s.load():
        fail('never reached Ready in %ds (overlay last said: %s)' % (args.timeout, s.phase()))
    else:
        print('==> Ready in %.0fs' % s.elapsed)
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
            grows = s.page.evaluate(
                "() => { const m = window.fcInstance;"
                " try { return !!(m && m.wasmMemory && m.wasmMemory.buffer"
                " && m.wasmMemory.grow); } catch (e) { return false; } }")
            # 2 GB, not growable, is the deliberate configuration: memory growth
            # changes emscripten's codegen and breaks the GL patch table (ROADMAP 6).
            print('==> heap: %s MB, growable=%s' % (heap, grows))
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
    s2.run_python(COUNT_DOCS_PY)
    r = s2.wait_for('FCDOCS', 120)
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
    return s


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
    ap.add_argument('--scenario', default='boot', choices=('boot', 'restore', 'dialog', 'imports', 'network', 'workflow', 'addons', 'addoninstall', 'fem', 'examples', 'workbenches', 'render', 'upgrade', 'all'))
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

            for _name, _fn in (
                ('boot', scenario_boot),
                ('restore', scenario_restore),
                ('dialog', scenario_dialog),
                ('imports', scenario_imports),
                ('network', scenario_network),
                ('workflow', scenario_workflow),
                ('addons', scenario_addons),
                ('fem', scenario_fem),
                ('examples', scenario_examples),
                ('workbenches', scenario_workbenches),
                ('addoninstall', scenario_addoninstall),
            ):
                if out_of_time or args.scenario not in (_name, 'all'):
                    continue
                out_of_time = run_scenario(_name, _fn)
            if args.scenario == 'render':
                out_of_time = run_scenario('render', scenario_render)
            if args.scenario == 'upgrade':
                out_of_time = run_scenario('upgrade', scenario_upgrade)
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

    # Say what was actually checked. A pass line that claims more than the run covered is
    # how a gate starts being trusted for things it never tested.
    did = {
        'boot': 'starts and does CAD work',
        'restore': 'gives work back after a reload',
        'dialog': 'can ask the user a question and use the answer',
        'imports': 'can import the Python packages its workbenches need',
        'network': 'can reach the web through the proxy',
        'workflow': 'can model: constrained sketch, pad, booleans, STEP, save and reopen',
        'addons': 'can reach the addon catalogue through the proxy',
        'all': 'starts, does CAD work, gives work back after a reload, can ask the user a '
               'question, has the Python packages its workbenches need, and can reach the '
               'web',
    }[args.scenario]
    print('==> boot gate passed: the application %s' % did)
    return 0


if __name__ == '__main__':
    sys.exit(main())
