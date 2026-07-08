import sys, os, traceback
def m(s): print("STEP "+s); sys.stdout.flush()
import FreeCAD as App
# FEM last (its trap aborts the wasm); rest first
order = ["AssemblyExample.FCStd","EngineBlock.FCStd","PartDesignExample.FCStd",
         "draft_test_objects.FCStd","BIMExample.FCStd","FEMExample.FCStd"]
d0 = "/freecad/examples/"
for fn in order:
    p = d0+fn
    if not os.path.exists(p):
        m("MISSING %s" % fn); continue
    try:
        doc = App.openDocument(p)
        try: doc.recompute()
        except Exception as re: m("RECOMPUTE-WARN %s %r" % (fn, re))
        nv=0; vol=0.0
        for o in doc.Objects:
            sh=getattr(o,"Shape",None)
            if sh is not None and hasattr(sh,"Volume"):
                try:
                    if sh.Volume>1e-9: nv+=1; vol+=sh.Volume
                except Exception: pass
        m("OK %-24s objs=%d solids=%d vol=%.1f" % (fn, len(doc.Objects), nv, vol))
        App.closeDocument(doc.Name)
    except Exception as e:
        m("FAIL %s %r" % (fn, e))
m("ALL DONE")
