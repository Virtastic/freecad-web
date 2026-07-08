import sys
def m(s): print("STEP "+s); sys.stdout.flush()
r={}
try:
    import numpy as np; r['numpy']=np.__version__
    assert abs(float(np.linalg.norm(np.array([3.,4.])))-5.0)<1e-9
except Exception as e: r['numpy']='FAIL %r'%e
try:
    import matplotlib; matplotlib.use("QtAgg"); import matplotlib.pyplot as plt
    r['matplotlib']=matplotlib.__version__+' '+matplotlib.get_backend()
except Exception as e: r['matplotlib']='FAIL %r'%e
try:
    import ctypes; CB=ctypes.CFUNCTYPE(ctypes.c_int,ctypes.c_int); r['ctypes']='closure=%d'%CB(lambda v:v+1)(41)
except Exception as e: r['ctypes']='FAIL %r'%e
try:
    from PIL import Image; import io; b=io.BytesIO(); Image.new("RGB",(8,8)).save(b,"PNG"); r['pillow']='png=%d'%len(b.getvalue())
except Exception as e: r['pillow']='FAIL %r'%e
try:
    import scipy; r['scipy']=scipy.__version__
except Exception as e: r['scipy']='(not ported: %s)'%type(e).__name__
for k in ('numpy','matplotlib','ctypes','pillow','scipy'): m("%-11s %s"%(k,r[k]))
m("STACK-DONE")
