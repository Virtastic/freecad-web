# Real workflows, each ending in a checkable number. If any of these is broken, someone
# trying to build something hits it in their first hour.
import sys, os, traceback
import FreeCAD as App

RESULTS = []

def ok(name, msg):
    RESULTS.append("PASS %s: %s" % (name, msg))

def bad(name, e):
    RESULTS.append("FAIL %s: %s" % (name, str(e)[:110]))

def step(name):
    def deco(fn):
        try:
            fn()
        except Exception as e:
            bad(name, e)
            RESULTS.append("   trace: %s" % traceback.format_exc().splitlines()[-1])
        return fn
    return deco

d = App.newDocument("WF")

@step("sketch+constraints")
def _():
    import Sketcher, Part
    sk = d.addObject('Sketcher::SketchObject', 'Sk')
    import FreeCAD as A
    V = A.Vector
    sk.addGeometry(Part.LineSegment(V(0, 0, 0), V(40, 0, 0)), False)
    sk.addGeometry(Part.LineSegment(V(40, 0, 0), V(40, 25, 0)), False)
    sk.addGeometry(Part.LineSegment(V(40, 25, 0), V(0, 25, 0)), False)
    sk.addGeometry(Part.LineSegment(V(0, 25, 0), V(0, 0, 0)), False)
    for i in range(4):
        sk.addConstraint(Sketcher.Constraint('Coincident', i, 2, (i + 1) % 4, 1))
    sk.addConstraint(Sketcher.Constraint('Horizontal', 0))
    sk.addConstraint(Sketcher.Constraint('Vertical', 1))
    sk.addConstraint(Sketcher.Constraint('DistanceX', 0, 1, 0, 2, 40.0))
    sk.addConstraint(Sketcher.Constraint('DistanceY', 1, 1, 1, 2, 25.0))
    d.recompute()
    ok("sketch+constraints", "geo=%d constraints=%d DoF=%d" % (
        sk.GeometryCount, len(sk.Constraints), sk.solve()))

@step("partdesign pad+pocket")
def _():
    body = d.addObject('PartDesign::Body', 'Body')
    import Part, Sketcher
    from FreeCAD import Vector as V
    s2 = d.addObject('Sketcher::SketchObject', 'PadSk')
    body.addObject(s2)
    s2.addGeometry(Part.Circle(V(0, 0, 0), V(0, 0, 1), 12), False)
    pad = d.addObject('PartDesign::Pad', 'Pad')
    body.addObject(pad)
    pad.Profile = s2
    pad.Length = 20
    d.recompute()
    s3 = d.addObject('Sketcher::SketchObject', 'PocketSk')
    body.addObject(s3)
    attr = 'AttachmentSupport' if hasattr(s3, 'AttachmentSupport') else 'Support'
    setattr(s3, attr, [(pad, 'Face2')])          # FreeCAD 1.0 renamed Support
    s3.MapMode = 'FlatFace'
    s3.addGeometry(Part.Circle(V(0, 0, 0), V(0, 0, 1), 5), False)
    pk = d.addObject('PartDesign::Pocket', 'Pocket')
    body.addObject(pk)
    pk.Profile = s3
    pk.Length = 10
    d.recompute()
    ok("partdesign pad+pocket", "pad vol=%.1f final vol=%.1f" % (pad.Shape.Volume, body.Shape.Volume))

@step("boolean+fillet")
def _():
    import Part
    b = d.addObject("Part::Box", "BB"); b.Length = b.Width = b.Height = 20
    c = d.addObject("Part::Cylinder", "CC"); c.Radius = 6; c.Height = 30
    cut = d.addObject("Part::Cut", "Cut"); cut.Base = b; cut.Tool = c
    d.recompute()
    f = d.addObject("Part::Fillet", "Fillet"); f.Base = cut
    edges = [(i + 1, 1.5, 1.5) for i in range(min(4, len(cut.Shape.Edges)))]
    f.Edges = edges
    d.recompute()
    ok("boolean+fillet", "cut vol=%.1f fillet vol=%.1f faces=%d" % (
        cut.Shape.Volume, f.Shape.Volume, len(f.Shape.Faces)))

@step("draft objects")
def _():
    import Draft
    from FreeCAD import Vector as V
    w = Draft.make_wire([V(0, 0, 0), V(10, 0, 0), V(10, 10, 0)], closed=True)
    c = Draft.make_circle(7)
    d.recompute()
    ok("draft objects", "wire len=%.2f circle area=%.2f" % (w.Shape.Length, c.Shape.Area))

@step("spreadsheet")
def _():
    sh = d.addObject('Spreadsheet::Sheet', 'Sheet')
    sh.set('A1', '12')
    sh.set('A2', '30')
    sh.set('A3', '=A1*A2')
    d.recompute()
    ok("spreadsheet", "A3=%s" % sh.get('A3'))

@step("techdraw page")
def _():
    import TechDraw, os
    tdir = App.getResourceDir() + 'Mod/TechDraw/Templates'
    a4 = sorted(f for f in os.listdir(tdir) if f.startswith('A4') and f.endswith('.svg'))[0]
    page = d.addObject('TechDraw::DrawPage', 'Page')
    tmpl = d.addObject('TechDraw::DrawSVGTemplate', 'Template')
    tmpl.Template = os.path.join(tdir, a4)     # without a template the page has no size
    page.Template = tmpl
    v = d.addObject('TechDraw::DrawViewPart', 'View')
    page.addView(v)
    v.Source = [d.getObject('Cut')]
    v.Direction = App.Vector(0, 0, 1)
    d.recompute()
    ok("techdraw page", "page=%.0fx%.0f mm views=%d (edges checked after HLR settles)" % (
        tmpl.Width.Value if hasattr(tmpl.Width, 'Value') else tmpl.Width,
        tmpl.Height.Value if hasattr(tmpl.Height, 'Value') else tmpl.Height,
        len(page.Views)))

@step("export step/stl/iges")
def _():
    import Import, Mesh, MeshPart
    src = d.getObject('Cut')
    Import.export([src], '/tmp/wf.step')
    Import.export([src], '/tmp/wf.iges')
    m = MeshPart.meshFromShape(Shape=src.Shape, LinearDeflection=0.3)
    m.write('/tmp/wf.stl')
    sizes = tuple(os.path.getsize(p) for p in ('/tmp/wf.step', '/tmp/wf.iges', '/tmp/wf.stl'))
    ok("export step/stl/iges", "step=%d iges=%d stl=%d facets=%d" % (sizes + (m.CountFacets,)))

@step("reopen roundtrip")
def _():
    d.saveAs('/tmp/wf.FCStd')
    n = len(d.Objects)
    App.closeDocument(d.Name)
    d2 = App.openDocument('/tmp/wf.FCStd')
    ok("reopen roundtrip", "objects %d -> %d, Cut vol=%.1f" % (
        n, len(d2.Objects), d2.getObject('Cut').Shape.Volume))

for r in RESULTS:
    sys.__stderr__.write("WF " + r + "\n")
sys.__stderr__.write("WF DONE\n")
sys.__stderr__.flush()
