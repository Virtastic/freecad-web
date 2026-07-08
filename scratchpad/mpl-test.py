import sys
def m(s): print("STEP "+s); sys.stdout.flush()
try:
    import matplotlib
    m("matplotlib %s imported" % matplotlib.__version__)
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    m("pyplot imported, backend=%s" % matplotlib.get_backend())
    import numpy as np
    fig = plt.figure()
    plt.hist(np.array([1.0,2,2,3,3,3,4,4,4,4]), bins=4, facecolor="blue")
    plt.xlabel("value"); plt.ylabel("count"); plt.title("FEM-style histogram")
    m("hist plotted")
    fig.canvas.draw()   # Agg rasterization (ft2font text render + agg paths)
    buf = fig.canvas.buffer_rgba()
    import numpy as _np
    arr = _np.asarray(buf)
    nonwhite = int((arr[:,:,:3] < 250).any(axis=2).sum())
    m("Agg rendered: %dx%d, non-white px=%d" % (arr.shape[1], arr.shape[0], nonwhite))
    m("MPL-OK" if nonwhite > 100 else "MPL-EMPTY")
except Exception as e:
    import traceback
    print("MPL-FAIL %r" % e); traceback.print_exc(); sys.stdout.flush()
