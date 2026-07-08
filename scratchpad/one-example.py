import sys, os
def m(s): print("STEP "+s); sys.stdout.flush()
import FreeCAD as App
fn = os.environ.get("FCEX","FEMExample.FCStd")
p = "/freecad/examples/"+fn
d = App.openDocument(p)
try: d.recompute()
except Exception as e: m("RECWARN %r" % e)
nv=0; vol=0.0
for o in d.Objects:
    sh=getattr(o,"Shape",None)
    if sh is not None:
        try:
            if not sh.isNull() and sh.Volume>1e-9: nv+=1; vol+=sh.Volume
        except Exception: pass
m("OK %s objs=%d solids=%d vol=%.1f" % (fn, len(d.Objects), nv, vol))
App.closeDocument(d.Name)
m("CLOSED")
