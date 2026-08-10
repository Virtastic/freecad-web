# Emits the list of bundled example basenames (no extension) for regression.js,
# which then opens each one itself. Must print exactly one EX-AVAIL line.
import sys, os
d = '/freecad/share/examples'
names = sorted(
    os.path.splitext(f)[0] for f in os.listdir(d) if f.endswith('.FCStd')
)
sys.__stderr__.write("EX-AVAIL %s\n" % (names,))
sys.__stderr__.flush()
