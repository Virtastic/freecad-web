import sys
def m(s): print("STEP "+s); sys.stdout.flush()
import FreeCAD as App
doc = App.openDocument("/freecad/examples/BIMExample.FCStd")
doc.recompute()
nv=0; vol=0.0; nulls=0
for o in doc.Objects:
    sh=getattr(o,"Shape",None)
    if sh is None: continue
    try:
        if sh.isNull(): nulls+=1; continue
        v=sh.Volume
        if v>1e-9: nv+=1; vol+=v
    except Exception:
        nulls+=1
m("BIM OK objs=%d solids=%d vol=%.1f nullshapes=%d" % (len(doc.Objects), nv, vol, nulls))
App.closeDocument(doc.Name)
m("closed OK")
