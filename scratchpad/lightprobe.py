# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) Virtastic
"""Render one lighting reference scene and save it, plus the numbers behind it.

Runs in BOTH FreeCADs: the desktop binary (`freecad.exe scratchpad/lightprobe.py`) and the
browser build (driven by scratchpad/lightcmp.js), so the same geometry, the same camera and
the same material produce two images that can be compared pixel for pixel. That is the only
honest way to answer "is the lighting the same as desktop".

The scene is chosen so shading is the ONLY variable: one sphere and one box, fixed colours,
no transparency, a fixed isometric camera and a fixed window size. A sphere is included
because it sweeps every normal direction, which is where a wrong light direction, a missing
specular term or a bad normal matrix shows up as a differently placed highlight.
"""
import json
import os
import sys

OUT = os.environ.get("FCWEB_LIGHT_OUT", "/tmp/lightprobe")   # desktop overrides it
SIZE = (900, 700)


def build(App, Gui):
    doc = App.newDocument("LightRef")
    sph = doc.addObject("Part::Sphere", "Sphere")
    sph.Radius = 20
    box = doc.addObject("Part::Box", "Box")
    box.Length = box.Width = box.Height = 26
    box.Placement.Base = App.Vector(30, -13, -13)
    # FCWEB_LIGHT_LAYOUT=swap puts the box at the origin and moves the sphere instead.
    # If a surface goes wrong when it moves, the normal matrix is picking up translation.
    if os.environ.get("FCWEB_LIGHT_LAYOUT") == "swap":
        box.Placement.Base = App.Vector(-13, -13, -13)
        sph.Placement.Base = App.Vector(-40, 0, 0)
    doc.recompute()

    # FCWEB_LIGHT_VARIANT=diffuse strips the ambient and specular terms, leaving the pure
    # diffuse term. Comparing both variants says WHICH term of the lighting model differs,
    # rather than only that the picture does.
    variant = os.environ.get("FCWEB_LIGHT_VARIANT", "full")
    for obj, colour in ((sph, (0.75, 0.75, 0.78)), (box, (0.75, 0.75, 0.78))):
        vo = obj.ViewObject
        vo.ShapeColor = colour
        vo.Transparency = 0
        vo.DisplayMode = "Shaded"          # no edges: shading only
        if variant == "diffuse":
            try:
                app = vo.ShapeAppearance[0]
                app.AmbientColor = (0.0, 0.0, 0.0)
                app.SpecularColor = (0.0, 0.0, 0.0)
                app.EmissiveColor = (0.0, 0.0, 0.0)
                app.Shininess = 0.0
                vo.ShapeAppearance = [app]
            except Exception as exc:
                sys.__stderr__.write("variant setup failed: %r\n" % (exc,))
    Gui.updateGui()

    view = Gui.activeDocument().activeView()
    view.setCameraType("Orthographic")
    # A fixed camera, written out rather than fitted, so both sides frame it identically.
    view.setCamera(
        "OrthographicCamera { viewportMapping ADJUST_CAMERA "
        "position 120 -120 90 orientation 0.51 0.21 0.83 1.35 "
        "nearDistance 10 farDistance 400 focalDistance 190 height 130 }"
    )
    Gui.updateGui()
    return doc, view


def report(App, Gui, where):
    """What the renderer was asked to do, so a difference in the image can be attributed."""
    out = {"version": ".".join(App.Version()[0:3]), "where": where,
           "variant": os.environ.get("FCWEB_LIGHT_VARIANT", "full"),
           "layout": os.environ.get("FCWEB_LIGHT_LAYOUT", "default")}
    try:
        from pivy import coin
        v = Gui.activeDocument().activeView()
        rm = v.getViewer().getSoRenderManager()
        out["transparency_type"] = int(rm.getGLRenderAction().getTransparencyType())
        sg = v.getSceneGraph()
        lights = []

        def walk(node, depth=0):
            if depth > 4:
                return
            name = str(node.getTypeId().getName().getString())
            if "Light" in name:
                entry = {"type": name}
                for field in ("intensity", "color", "direction", "location"):
                    f = getattr(node, field, None)
                    if f is not None:
                        try:
                            entry[field] = str(f.getValue())
                        except Exception:
                            pass
                lights.append(entry)
            if hasattr(node, "getNumChildren"):
                for i in range(node.getNumChildren()):
                    walk(node.getChild(i), depth + 1)

        walk(sg)
        out["lights"] = lights

        # The box's own normals and coordinates, straight from its view provider's scene
        # graph. Identical on both sides means the geometry is right and the difference is
        # in how normals reach the GPU; different means FreeCAD built different normals.
        box = App.ActiveDocument.getObject("Box")
        found = {}

        def grab(node, depth=0):
            if depth > 10:
                return
            name = str(node.getTypeId().getName().getString())
            if name == "Normal" and "normals" not in found:
                n = coin.cast(node, "SoNormal")
                found["normals"] = [[round(n.vector[i][k], 3) for k in range(3)]
                                    for i in range(n.vector.getNum())]
            if name == "Coordinate3" and "coords" not in found:
                c = coin.cast(node, "SoCoordinate3")
                found["coords"] = c.point.getNum()
            if name in ("SoBrepFaceSet", "BrepFaceSet") and "faceset" not in found:
                f = node
                try:
                    found["faceset"] = {"partIndex": [f.partIndex[i] for i in range(f.partIndex.getNum())],
                                        "coordIndex_len": f.coordIndex.getNum()}
                except Exception as exc:
                    found["faceset"] = repr(exc)[:80]
            if name == "NormalBinding" and "normalBinding" not in found:
                found["normalBinding"] = int(coin.cast(node, "SoNormalBinding").value.getValue())
            if hasattr(node, "getNumChildren"):
                for i in range(node.getNumChildren()):
                    grab(node.getChild(i), depth + 1)

        grab(box.ViewObject.RootNode)
        out["box_geometry"] = found
    except Exception as exc:  # pivy differs slightly between builds; the image still counts
        out["probe_error"] = repr(exc)[:200]
    return out


def main():
    import FreeCAD as App
    import FreeCADGui as Gui

    where = "wasm" if sys.platform == "emscripten" else "desktop"
    doc, view = build(App, Gui)
    info = report(App, Gui, where)

    if where == "desktop":
        os.makedirs(os.path.dirname(OUT + ".png") or ".", exist_ok=True)
        view.saveImage(OUT + ".png", SIZE[0], SIZE[1], "Current")
        info["image"] = OUT + ".png"
        # saveImage renders offscreen, and there Coin adds a fourth light (a copy of the
        # back light) that the live viewport never has (measured 2026-09-22). What a user
        # sees is the live viewport, so grab that too, straight off the screen.
        from PySide import QtGui
        Gui.updateGui()
        mw = Gui.getMainWindow()
        QtGui.QApplication.primaryScreen().grabWindow(mw.winId()).save(OUT + "-live.png")
        info["live_image"] = OUT + "-live.png"
    with open(OUT + ".json", "w") as fh:
        json.dump(info, fh)
    sys.__stderr__.write("LIGHTPROBE " + json.dumps(info) + "\n")
    sys.__stderr__.flush()


main()
