"""ViewProviderExt.cpp section of patches/freecad.patch, regenerated wholesale (CRLF file):
  1. InParallel = false on wasm (measured slower, see comment), and
  2. the visual tessellation of a large shape runs on the load worker (Base/FcwebWorker.h)
     while the main thread parks -- the tab keeps painting and the input queue stays queued
     (the park holds Qt's resume slot, gl_legacy_stubs.c), so no C++ runs on the main thread
     against the shape being meshed. The 42 MB a2plus assembly's largest part froze the tab
     for ~5 s per open at that call (yield-probe.py, 2026-09-15)."""
import io, os, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REL = 'src/Mod/Part/Gui/ViewProviderExt.cpp'
P = os.path.join(ROOT, 'patches', 'freecad.patch')
WORK = os.path.join(ROOT, 'scratchpad', 'vpext-work')

INCLUDES_OLD = b'#include <BRepMesh_IncrementalMesh.hxx>\n'
INCLUDES_NEW = b'''#include <BRepMesh_IncrementalMesh.hxx>
'''

PAR_OLD = b'    meshParams.InParallel = Standard_True;\n'
PAR_NEW = b'''#if defined(__EMSCRIPTEN__)
    // wasm: serial. Measured 2026-09-15 on the 42 MB a2plus assembly (scratchpad/yield-probe.py,
    // same engine, ?occthreads=N): InParallel with the bounded 6-thread OSD_ThreadPool from
    // AppPart.cpp opened it in 31.4 s, with 3 threads 21.7 s, serial 21.6 s -- and the
    // longest frozen stretch (one part's mesh) did not shrink either. The per-face tasks are
    // small and the main thread's wait for the pool is a futex spin on this platform, so the
    // parallel path only adds synchronisation. The pool still serves the algorithms that
    // benefit (booleans, checks); the visual mesh does not.
    meshParams.InParallel = Standard_False;
#else
    meshParams.InParallel = Standard_True;
#endif
'''

MESH_OLD = b'    BRepMesh_IncrementalMesh(shape, meshParams);\n'
MESH_NEW = b'''#if defined(__EMSCRIPTEN__)
    // FCWEB: a large shape is meshed on the load worker (Base/FcwebWorker.h) while the main
    // thread parks until the worker wakes it. The park holds Qt's
    // resume slot, so DOM events and timers QUEUE instead of running C++ against the shape
    // being meshed, the page compositor keeps painting, and Chrome never calls the tab
    // hung. The GIL is released for the wait like Document.cpp's yield point does (other
    // Python activations may need it; the bridge serialises calls behind this one). Only
    // legal on a promising stack (fcweb_yield_ok: a load, a recompute from real input), and
    // only worth a thread for shapes with many faces: the largest part of the a2plus
    // assembly froze the tab ~5 s at this call (yield-probe.py, 2026-09-15).
    int fcwebFaces = 0;
    for (TopExp_Explorer xp(shape, TopAbs_FACE); xp.More() && fcwebFaces < 64; xp.Next()) {
        ++fcwebFaces;
    }
    if (fcwebFaces >= 64 && Base::FcwebWorker::usable()) {
        Base::FcwebWorker::run([&]() { BRepMesh_IncrementalMesh(shape, meshParams); });
    }
    else {
        BRepMesh_IncrementalMesh(shape, meshParams);
    }
#else
    BRepMesh_IncrementalMesh(shape, meshParams);
#endif
'''

src = io.open(os.path.join(ROOT, 'scratchpad', 'tree113', REL), 'rb').read()
assert b'\r\n' in src
mod = src
INC_OLD = b'#include "ViewProviderPartExtPy.h"\n'
INC_NEW = INC_OLD + b'#if defined(__EMSCRIPTEN__)\n#include <Base/FcwebWorker.h>\n#endif\n'
for old, new in [(INC_OLD, INC_NEW), (PAR_OLD, PAR_NEW), (MESH_OLD, MESH_NEW)]:
    old = old.replace(b'\n', b'\r\n'); new = new.replace(b'\n', b'\r\n')
    assert mod.count(old) == 1, old[:40]
    mod = mod.replace(old, new)
a = os.path.join(WORK, 'a', REL); b = os.path.join(WORK, 'b', REL)
os.makedirs(os.path.dirname(a), exist_ok=True); os.makedirs(os.path.dirname(b), exist_ok=True)
io.open(a, 'wb').write(src); io.open(b, 'wb').write(mod)
r = subprocess.run(['diff', '-ruNp', 'a/' + REL, 'b/' + REL], cwd=WORK, capture_output=True)
assert r.returncode == 1, r.stderr
body = r.stdout.split(b'\n', 2)[2]
hdr = b'diff -ruNp a/' + REL.encode() + b' b/' + REL.encode() + b'\n'
sec = hdr + b'--- a/' + REL.encode() + b'\n+++ b/' + REL.encode() + b'\n' + body
raw = io.open(P, 'rb').read()
if hdr in raw:
    i = raw.index(hdr); j = raw.index(b'\ndiff -ruNp ', i + 10) + 1
    raw = raw[:i] + sec + raw[j:]
else:
    anchor = b'diff -ruNp a/src/Mod/PartDesign/Gui/ViewProviderDatum.cpp'
    i = raw.index(anchor); raw = raw[:i] + sec + raw[i:]
io.open(P, 'wb').write(raw)
io.open(os.path.join(WORK, 'sec.diff'), 'wb').write(sec)
r = subprocess.run([sys.executable, os.path.join(ROOT, 'tools', 'check-patch-applies.py'), os.path.join(WORK, 'sec.diff'), os.path.join(WORK, 'a')], capture_output=True, text=True)
print(r.stdout.strip()[-200:], r.stderr.strip()[-200:])
sys.exit(r.returncode)
