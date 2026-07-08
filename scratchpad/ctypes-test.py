import sys
def m(s): print("STEP "+s); sys.stdout.flush()
try:
    import ctypes
    m("ctypes imported")
    # basic ctypes: create a c_int, call a libc-ish function via a CFUNCTYPE closure
    x = ctypes.c_int(42)
    m("c_int value=%d" % x.value)
    CB = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_int)
    def cb(v): return v*2
    f = CB(cb)   # closure -> needs libffi ffi_prep_closure (ALLOW_TABLE_GROWTH)
    m("CFUNCTYPE closure result=%d" % f(21))
    m("CTYPES-OK")
except Exception as e:
    import traceback; print("CTYPES-FAIL %r" % e); traceback.print_exc(); sys.stdout.flush()
