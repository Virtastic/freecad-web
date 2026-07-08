import sys
def m(s): print("STEP "+s); sys.stdout.flush()
try:
    from femtaskpanels import task_result_mechanical as trm
    m("FEM task panel imported; plt available=%s" % (trm.plt is not None))
    if trm.plt is not None:
        import numpy as np
        trm.plt.figure("FEM")
        trm.plt.hist(np.array([1.0,2,2,3,3,3,4,4]), bins=4, facecolor="blue")
        trm.plt.xlabel("MPa"); trm.plt.title("Stress histogram")
        fig = trm.plt.gcf(); fig.canvas.draw()
        buf = np.asarray(fig.canvas.buffer_rgba())
        nz = int((buf[:,:,:3] < 250).any(axis=2).sum())
        m("FEM histogram rendered non-white px=%d backend=%s" % (nz, trm.matplotlib.get_backend()))
        m("FEM-MPL-OK")
    else:
        m("FEM-MPL-NO-PLT")
except Exception as e:
    import traceback; print("FEM-MPL-FAIL %r" % e); traceback.print_exc(); sys.stdout.flush()
