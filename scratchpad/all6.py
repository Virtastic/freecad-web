import sys, os
def m(s): print("STEP "+s); sys.stdout.flush()
import FreeCAD as App
for fn in ["AssemblyExample","EngineBlock","PartDesignExample","draft_test_objects","BIMExample","FEMExample"]:
    p="/freecad/examples/%s.FCStd"%fn
    try:
        d=App.openDocument(p)
        try: d.recompute()
        except Exception as e: pass
        nv=0; vol=0.0
        for o in d.Objects:
            sh=getattr(o,"Shape",None)
            if sh is not None:
                try:
                    if not sh.isNull() and sh.Volume>1e-9: nv+=1; vol+=sh.Volume
                except Exception: pass
        m("OK %-22s objs=%3d solids=%d vol=%.0f" % (fn, len(d.Objects), nv, vol))
        App.closeDocument(d.Name)
    except Exception as e:
        m("FAIL %s %r" % (fn, e))
m("ALL6-DONE")
