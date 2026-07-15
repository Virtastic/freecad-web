# Comprehensive FreeCAD-wasm functional test. Emits FCTEST|name|PASS/FAIL|detail
# to stderr (-> #log). Each test isolated in try/except so one failure never
# aborts the suite. Mirrors real desktop workflows across workbenches.
import sys, traceback
_TESTS = {}
def _emit(name, ok, detail=''):
    sys.__stderr__.write('FCTEST|%s|%s|%s\n' % (name, 'PASS' if ok else 'FAIL', str(detail)[:200]))
    sys.__stderr__.flush()
def T(name):
    def deco(fn):
        _TESTS[name] = fn   # register only; JS invokes each individually
        return fn
    return deco
def _ft_run(name):
    fn = _TESTS.get(name)
    if fn is None:
        _emit(name, False, 'no such test'); return
    try:
        d = fn() or ''
        _emit(name, True, d)
    except Exception as e:
        _emit(name, False, repr(e) + ' :: ' + traceback.format_exc().splitlines()[-1])

import FreeCAD as App, FreeCADGui as Gui, Part
D = App.newDocument('FT')

@T('part.primitives')
def _():
    b = D.addObject('Part::Feature','B'); b.Shape = Part.makeBox(10,10,10)
    c = D.addObject('Part::Feature','C'); c.Shape = Part.makeCylinder(4,12)
    s = D.addObject('Part::Feature','S'); s.Shape = Part.makeSphere(6)
    co= D.addObject('Part::Feature','Co'); co.Shape = Part.makeCone(5,0,10)
    to= D.addObject('Part::Feature','To'); to.Shape = Part.makeTorus(10,3)
    D.recompute()
    assert all(o.Shape.isValid() for o in (b,c,s,co,to)), 'invalid shape'
    return 'box cyl sphere cone torus ok, vols=%.1f/%.1f' % (b.Shape.Volume, s.Shape.Volume)

@T('part.boolean')
def _():
    a = Part.makeBox(10,10,10); b = Part.makeSphere(7)
    f = a.fuse(b); c = a.cut(b); i = a.common(b)
    assert f.isValid() and c.isValid() and i.isValid()
    o = D.addObject('Part::Feature','Bool'); o.Shape = c; D.recompute()
    return 'fuse/cut/common ok, cutVol=%.1f' % c.Volume

@T('part.fillet_chamfer')
def _():
    bx = Part.makeBox(10,10,10)
    fl = bx.makeFillet(1.0, bx.Edges)
    ch = bx.makeChamfer(1.0, bx.Edges)
    assert fl.isValid() and ch.isValid()
    return 'fillet+chamfer ok'

@T('partdesign.pad_pocket')
def _():
    import Sketcher
    body = D.addObject('PartDesign::Body','Body')
    sk = body.newObject('Sketcher::SketchObject','Sketch')
    sk.addGeometry(Part.LineSegment(App.Vector(0,0,0),App.Vector(20,0,0)),False)
    sk.addGeometry(Part.LineSegment(App.Vector(20,0,0),App.Vector(20,20,0)),False)
    sk.addGeometry(Part.LineSegment(App.Vector(20,20,0),App.Vector(0,20,0)),False)
    sk.addGeometry(Part.LineSegment(App.Vector(0,20,0),App.Vector(0,0,0)),False)
    D.recompute()
    pad = body.newObject('PartDesign::Pad','Pad'); pad.Profile = sk; pad.Length = 10
    D.recompute()
    assert pad.Shape.isValid() and pad.Shape.Volume > 0, 'pad invalid'
    return 'pad vol=%.1f' % pad.Shape.Volume

@T('sketcher.constraints')
def _():
    import Sketcher
    sk = D.addObject('Sketcher::SketchObject','ConSketch')
    i1 = sk.addGeometry(Part.LineSegment(App.Vector(0,0,0),App.Vector(30,0,0)),False)
    sk.addConstraint(Sketcher.Constraint('Horizontal',i1))
    sk.addConstraint(Sketcher.Constraint('DistanceX',i1,1,i1,2,25.0))
    D.recompute()
    return 'constraints n=%d' % sk.ConstraintCount

@T('draft.objects')
def _():
    import Draft
    l = Draft.make_line(App.Vector(0,0,0), App.Vector(10,10,0))
    c = Draft.make_circle(5.0)
    r = Draft.make_rectangle(20,10)
    D.recompute()
    assert l and c and r
    return 'line circle rect ok'

@T('mesh.from_shape')
def _():
    import Mesh, MeshPart
    bx = Part.makeBox(10,10,10)
    m = MeshPart.meshFromShape(Shape=bx, LinearDeflection=0.5, AngularDeflection=0.3)
    mo = D.addObject('Mesh::Feature','Mesh'); mo.Mesh = m; D.recompute()
    assert m.CountFacets > 0, 'no facets'
    return 'facets=%d points=%d' % (m.CountFacets, m.CountPoints)

@T('spreadsheet.cells')
def _():
    sh = D.addObject('Spreadsheet::Sheet','Sheet')
    sh.set('A1','10'); sh.set('A2','20'); sh.set('A3','=A1+A2')
    D.recompute()
    v = sh.get('A3')
    assert str(v) in ('30','30.0'), 'got %r' % v
    return 'A3=%s' % v

@T('draw.techdraw_page')
def _():
    import TechDraw
    pg = D.addObject('TechDraw::DrawPage','Page')
    tmpl = D.addObject('TechDraw::DrawSVGTemplate','Template')
    pg.Template = tmpl
    D.recompute()
    return 'page created'

@T('doc.save_load')
def _():
    import os
    box = D.addObject('Part::Feature','SaveBox'); box.Shape = Part.makeBox(5,5,5)
    D.recompute()
    path = '/tmp/fttest.FCStd'
    D.saveAs(path)
    assert os.path.exists(path), 'file not written'
    # load from a COPY, not D's own file — openDocument on the active doc's file
    # reloads/invalidates D and breaks later tests that share it.
    import shutil; path2 = '/tmp/fttest_copy.FCStd'; shutil.copy(path, path2)
    D2 = App.openDocument(path2)
    n = len(D2.Objects)
    App.closeDocument(D2.Name)
    App.setActiveDocument(D.Name)
    return 'saved+loaded objs=%d size=%d' % (n, os.path.getsize(path))

@T('io.step_export_import')
def _():
    import os
    bx = D.addObject('Part::Feature','StepBox'); bx.Shape = Part.makeBox(8,8,8)
    D.recompute()
    p = '/tmp/fttest.step'
    Part.export([bx], p)
    assert os.path.exists(p) and os.path.getsize(p) > 100, 'step not written'
    sh = Part.Shape(); sh.read(p)
    assert sh.isValid() and sh.Volume > 0
    return 'step vol=%.1f size=%d' % (sh.Volume, os.path.getsize(p))

@T('io.stl_export')
def _():
    import os, Mesh, MeshPart
    m = MeshPart.meshFromShape(Shape=Part.makeSphere(5), LinearDeflection=0.3)
    p = '/tmp/fttest.stl'; m.write(p)
    assert os.path.exists(p) and os.path.getsize(p) > 100
    return 'stl size=%d' % os.path.getsize(p)

@T('undo_redo')
def _():
    D.openTransaction('addU')
    u = D.addObject('Part::Feature','UndoBox'); u.Shape = Part.makeBox(3,3,3)
    D.commitTransaction(); D.recompute()
    before = len(D.Objects)
    D.undo(); after_u = len(D.Objects)
    D.redo(); after_r = len(D.Objects)
    assert after_u == before-1 and after_r == before, 'undo=%d redo=%d before=%d'%(after_u,after_r,before)
    return 'undo/redo ok'

sys.__stderr__.write('FCTEST|__REGISTERED__|PASS|%d tests: %s\n' % (len(_TESTS), ','.join(_TESTS.keys()))); sys.__stderr__.flush()
