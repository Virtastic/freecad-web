"""PropertyTopoShape.cpp section of patches/freecad.patch (CRLF file): the BRep text parse of a
restored shape runs on a worker thread while the main thread parks (same shape as the
worker tessellation in ViewProviderExt.cpp). After the tessellation moved off the main
thread the longest frozen stretch of the a2plus open was 3.4 s of BRepTools::Read --
istream/Strtod/GeomTools::GetReal in the profile (gpu-open-profile.py, 2026-09-16)."""
import io, os, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REL = 'src/Mod/Part/App/PropertyTopoShape.cpp'
P = os.path.join(ROOT, 'patches', 'freecad.patch')
WORK = os.path.join(ROOT, 'scratchpad', 'brep-work')

INC_OLD = b'#include <BRepTools.hxx>\n'
INC_NEW = b'''#include <BRepTools.hxx>
#if defined(__EMSCRIPTEN__)
#include <atomic>
#include <exception>
#include <thread>
#include <emscripten/threading.h>
// FCWEB: gl_legacy_stubs.c -- park one browser turn on a promising stack (see loadFromStream).
extern "C" int fcweb_yield_ok(void);
extern "C" void fcweb_wait_flag(volatile int* flag);
#endif
'''

READ_OLD = b'''        BRep_Builder builder;
        TopoDS_Shape shape;
        BRepTools::Read(shape, reader, builder);
        setValue(shape);
'''
READ_NEW = b'''        BRep_Builder builder;
        TopoDS_Shape shape;
#if defined(__EMSCRIPTEN__)
        // FCWEB: the BRep text parse runs on a worker thread while the main thread parks one
        // until the worker wakes it (gl_legacy_stubs.c fcweb_wait_flag). The park holds Qt's
        // resume slot, so events queue instead of running C++ on the main thread meanwhile,
        // and the page keeps painting. Only the worker touches the reader's zip stream until
        // the join. The GIL is released for the wait as Document.cpp's yield point does.
        // Legal only on a promising stack (a load through the Python bridge). The largest
        // part of the a2plus assembly froze the tab 3.4 s here (gpu-open-profile.py,
        // 2026-09-16); small shapes cost a thread spawn and one turn.
        if (fcweb_yield_ok()) {
            std::atomic<int> fcwebDone {0};
            std::exception_ptr fcwebErr;
            std::thread fcwebParser([&]() {
                try {
                    BRepTools::Read(shape, reader, builder);
                }
                catch (...) {
                    fcwebErr = std::current_exception();
                }
                fcwebDone = 1;
                emscripten_futex_wake(&fcwebDone, 1);
            });
            PyThreadState* fcwebTs = PyGILState_Check() ? PyEval_SaveThread() : nullptr;
            fcweb_wait_flag(reinterpret_cast<volatile int*>(&fcwebDone));
            if (fcwebTs) {
                PyEval_RestoreThread(fcwebTs);
            }
            fcwebParser.join();
            if (fcwebErr) {
                std::rethrow_exception(fcwebErr);
            }
        }
        else {
            BRepTools::Read(shape, reader, builder);
        }
#else
        BRepTools::Read(shape, reader, builder);
#endif
        setValue(shape);
'''

src = io.open(os.path.join(ROOT, 'scratchpad', 'tree113', REL), 'rb').read()
assert b'\r\n' in src
mod = src
for old, new in [(INC_OLD, INC_NEW), (READ_OLD, READ_NEW)]:
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
    anchor = b'diff -ruNp a/src/Mod/Part/Gui/'
    i = raw.index(anchor); raw = raw[:i] + sec + raw[i:]
io.open(P, 'wb').write(raw)
io.open(os.path.join(WORK, 'sec.diff'), 'wb').write(sec)
r = subprocess.run([sys.executable, os.path.join(ROOT, 'tools', 'check-patch-applies.py'), os.path.join(WORK, 'sec.diff'), os.path.join(WORK, 'a')], capture_output=True, text=True)
print(r.stdout.strip()[-200:], r.stderr.strip()[-200:])
sys.exit(r.returncode)
