import sys
def m(s): print("STEP "+s); sys.stdout.flush()
import FreeCAD as App
d = App.openDocument("/freecad/examples/FEMExample.FCStd")
try: d.recompute()
except Exception as e: m("RECWARN %r" % e)
nv=0; vol=0.0
for o in d.Objects:
    sh=getattr(o,"Shape",None)
    if sh is not None:
        try:
            if not sh.isNull() and sh.Volume>1e-9: nv+=1; vol+=sh.Volume
        except Exception: pass
m("OK FEMExample objs=%d solids=%d vol=%.1f" % (len(d.Objects), nv, vol))
App.closeDocument(d.Name)
m("CLOSED")
