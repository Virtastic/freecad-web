import sys, os
def m(s): print("STEP "+s); sys.stdout.flush()
import FreeCAD as App
rd = App.getResourceDir()
m("resourceDir=%r" % rd)
base = rd + "Mod/Fem/Resources/symbols/"
m("symdir=%r exists=%s" % (base, os.path.isdir(base)))
try:
    m("listing=%r" % (os.listdir(base)[:6] if os.path.isdir(base) else "NO DIR"))
except Exception as e:
    m("listfail=%r" % e)
for f in ("ConstraintFixed.iv","ConstraintForce.iv","ConstraintDisplacement.iv"):
    m("%s exists=%s" % (f, os.path.exists(base+f)))
