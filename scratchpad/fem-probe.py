import sys
def m(s): print("FEMSTEP "+s); sys.stdout.flush()
m("begin")
import FreeCAD as App
m("App imported")
# open WITHOUT gui viewproviders first? openDocument creates VPs in GUI build.
d = App.openDocument("/freecad/examples/FEMExample.FCStd")
m("opened doc objs=%d" % len(d.Objects))
for o in d.Objects:
    m("obj %s :: %s" % (o.Name, o.TypeId))
m("listing done; now recompute")
d.recompute()
m("recompute done")
App.closeDocument(d.Name)
m("closed OK")
