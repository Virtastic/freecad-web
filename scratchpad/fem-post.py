import sys
def m(s): print("STEP "+s); sys.stdout.flush()
import FreeCAD as App
d = App.openDocument("/freecad/examples/FEMExample.FCStd")
m("opened objs=%d" % len(d.Objects))
# find the FemPostPipeline objects and inspect their data
posts = [o for o in d.Objects if 'FemPost' in o.TypeId]
m("post objects=%d :: %s" % (len(posts), ",".join(o.Name for o in posts)))
for o in posts:
    # touch + recompute to trigger regeneration
    try: o.touch()
    except Exception: pass
d.recompute()
for o in posts:
    # inspect what data the pipeline holds after recompute
    info = []
    for attr in ('Data','Frames','NumberOfPoints'):
        if hasattr(o, attr): info.append("%s=%r" % (attr, getattr(o, attr)))
    # try the python API to get point count
    try:
        obj = o.getObject() if hasattr(o,'getObject') else o
    except Exception: obj=o
    m("POST %s type=%s attrs=[%s]" % (o.Name, o.TypeId, "; ".join(info)[:120]))
m("DONE")
App.closeDocument(d.Name)
