import sys
def m(s): print("STEP "+s); sys.stdout.flush()
# ctypes
try:
    import ctypes
    CB=ctypes.CFUNCTYPE(ctypes.c_int,ctypes.c_int); f=CB(lambda v:v*3)
    m("ctypes OK closure(7)=%d" % f(7))
except Exception as e:
    m("ctypes FAIL %r" % e)
# Pillow
try:
    from PIL import Image
    import io
    img=Image.new("RGB",(32,16),(200,50,50))
    buf=io.BytesIO(); img.save(buf,"PNG"); n=len(buf.getvalue())
    m("PIL OK PNG bytes=%d" % n)
except Exception as e:
    import traceback; m("PIL FAIL %r" % e); traceback.print_exc()
# matplotlib savefig PNG (needs PIL)
try:
    import matplotlib; matplotlib.use("Agg")
    import matplotlib.pyplot as plt, numpy as np, io
    plt.figure(); plt.hist(np.arange(20.0),bins=5); 
    b=io.BytesIO(); plt.savefig(b,format="png"); m("matplotlib savefig PNG bytes=%d" % len(b.getvalue()))
except Exception as e:
    import traceback; m("MPL-PNG FAIL %r" % e); traceback.print_exc()
m("FINAL-DEPS-DONE")
