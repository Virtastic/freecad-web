import sys
def m(s): print("STEP "+s); sys.stdout.flush()
import FreeCAD as App
m("opening FEMExample")
d = App.openDocument("/freecad/examples/FEMExample.FCStd")
m("OPENED objs=%d" % len(d.Objects))
d.recompute()
m("recomputed")
# count objects by having a shape/data
fem = [o for o in d.Objects if 'Fem' in o.TypeId]
m("FEM objs=%d types=%s" % (len(fem), ",".join(sorted(set(o.TypeId.split('::')[-1] for o in fem)))))
App.closeDocument(d.Name)
m("FEM-EXAMPLE-OK closed")
