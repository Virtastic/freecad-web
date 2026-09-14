"""Desktop FreeCAD 1.1.3 (the extracted official Windows build) running the SAME stimulus as
scratchpad/bench-all.py against the same example files, on the same machine, same session:
10 view-API changes each followed by updateGui() -> ms per change, plus 60 small camera
rotations (what a mouse drag costs the renderer) -> ms per frame.

    <fcdesk>/bin/freecad.exe scratchpad/desk-bench.py

Writes scratchpad/desk-bench.json and quits.
"""
import json
import os
import time
import traceback

import FreeCAD
import FreeCADGui
from PySide import QtCore, QtWidgets  # FreeCAD's PySide shim

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'desk-bench.json')
EXAMPLES = os.path.join(FreeCAD.getResourceDir(), 'examples')
FILES = ['ArchDetail', 'AssemblyExample', 'BIMExample', 'EngineBlock', 'FEMExample',
         'PartDesignExample', 'draft_test_objects']
results = {}


def bench_one(name):
    res = {}
    t0 = time.time()
    doc = FreeCAD.openDocument(os.path.join(EXAMPLES, name + '.FCStd'))
    doc.recompute()
    FreeCADGui.updateGui()
    res['open_s'] = round(time.time() - t0, 2)
    mw = FreeCADGui.getMainWindow()
    mdi = mw.findChild(QtWidgets.QMdiArea)
    sub = mdi.activeSubWindow() if mdi else None
    if sub:
        sub.showMaximized()
    FreeCADGui.activateView('Gui::View3DInventor', True)
    FreeCADGui.updateGui()
    v = FreeCADGui.activeDocument().activeView()
    (getattr(v, 'viewAxonometric', None) or v.viewIsometric)()
    FreeCADGui.SendMsgToActiveView('ViewFit')
    for _ in range(4):
        FreeCADGui.updateGui()
    res['objects'] = len(doc.Objects)
    res['visible'] = sum(1 for o in doc.Objects if getattr(o, 'ViewObject', None) and o.ViewObject.Visibility)
    # 1. the view-API stimulus, exactly bench-all's VIEWS_PY
    calls = ('viewIsometric', 'viewFront', 'viewTop', 'viewRight', 'viewRear')
    t0 = time.time()
    for i in range(10):
        getattr(v, calls[i % len(calls)])()
        FreeCADGui.updateGui()
    res['views_ms_per_change'] = round((time.time() - t0) * 100.0, 1)
    # 2. a drag: 60 small rotations of the camera, one frame each
    (getattr(v, 'viewAxonometric', None) or v.viewIsometric)()
    FreeCADGui.SendMsgToActiveView('ViewFit')
    FreeCADGui.updateGui()
    rot0 = v.getCameraOrientation()
    t0 = time.time()
    for i in range(60):
        r = FreeCAD.Rotation(FreeCAD.Vector(0, 0, 1), 1.5 * (i + 1)).multiply(rot0)
        v.setCameraOrientation(r)
        FreeCADGui.updateGui()
    res['drag_ms_per_frame'] = round((time.time() - t0) * 1000.0 / 60.0, 1)
    res['drag_fps'] = round(60.0 / max(1e-6, time.time() - t0), 1)
    FreeCAD.closeDocument(doc.Name)
    FreeCADGui.updateGui()
    return res


def run():
    mw = FreeCADGui.getMainWindow()
    mw.resize(1707, 932)
    FreeCADGui.updateGui()
    time.sleep(1)
    FreeCADGui.updateGui()
    for name in FILES:
        try:
            results[name] = bench_one(name)
        except Exception:
            results[name] = {'error': traceback.format_exc()[-400:]}
        with open(OUT, 'w') as fh:
            json.dump(results, fh, indent=1)
    with open(OUT, 'w') as fh:
        json.dump(results, fh, indent=1)
    QtWidgets.QApplication.quit()


QtCore.QTimer.singleShot(3000, run)
