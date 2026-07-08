import sys
def m(s): print("STEP "+s); sys.stdout.flush()
import FreeCAD as App
d = App.openDocument("/freecad/examples/FEMExample.FCStd")
posts = [o for o in d.Objects if 'FemPost' in o.TypeId]
m("post objs=%d" % len(posts))
for o in posts:
    n = -1
    try:
        # FemPostObject exposes the vtk dataset point count via getObject/Data
        if hasattr(o,'Data') and o.Data is not None:
            n = o.Data.GetNumberOfPoints() if hasattr(o.Data,'GetNumberOfPoints') else -2
    except Exception as e:
        n = "err:%r" % e
    m("POST %s type=%s points=%s" % (o.Name, o.TypeId.split('::')[-1], n))
m("DONE")
