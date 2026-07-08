import sys
def m(s): print("STEP "+s); sys.stdout.flush()
import FreeCAD as App
doc = App.openDocument("/freecad/examples/BIMExample.FCStd")
m("opened objs=%d" % len(doc.Objects))
# find objects whose stored Shape is already invalid (no recompute)
bad=0
for o in doc.Objects:
    sh=getattr(o,"Shape",None)
    if sh is not None and hasattr(sh,"isValid"):
        try:
            if not sh.isValid():
                bad+=1; m("INVALID %s %s nulls=%s" % (o.Name,o.TypeId, sh.isNull()))
        except Exception as e:
            m("SHAPEERR %s %s %r" % (o.Name,o.TypeId,e))
m("invalid-shape objects=%d" % bad)
# now try the recompute that failed, report the first erroring object
try:
    doc.recompute()
    m("doc recompute OK")
except Exception as e:
    m("doc recompute FAIL %r" % e)
errs=[(o.Name,o.TypeId) for o in doc.Objects if o.State and 'Error' in o.State]
m("error-state objs=%r" % errs[:10])
