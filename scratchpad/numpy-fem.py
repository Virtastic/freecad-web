import sys, traceback
def line(s): print("STEP "+s); sys.stdout.flush()
try:
    import numpy as np
    line("numpy imported version=%s" % np.__version__)
    a = np.arange(12, dtype=float).reshape(3,4)
    line("array ok sum=%.1f mean=%.2f" % (a.sum(), a.mean()))
    b = np.linalg.norm(np.array([3.0,4.0]))
    line("linalg.norm([3,4])=%.1f" % b)
    c = np.fft.fft(np.array([1.0,0,0,0]))
    line("fft ok c0=%.1f" % c[0].real)
except Exception as e:
    print("FAIL numpy: %r" % e); traceback.print_exc(); sys.stdout.flush()

# FEMExample
try:
    import FreeCAD as App
    d = App.openDocument("/freecad/examples/FEMExample.FCStd")
    d.recompute()
    line("FEMExample OK objs=%d" % len(d.Objects))
    App.closeDocument(d.Name)
except Exception as e:
    print("FAIL FEMExample: %r" % e); traceback.print_exc(); sys.stdout.flush()
print("STEP done"); sys.stdout.flush()
