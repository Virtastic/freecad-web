"""Coin: cache the per-thread soshape_staticdata lookup in a thread_local (wasm only).

soshape_get_staticdata() goes through SbStorage::get() -> cc_storage_get(), which takes a
mutex and looks the calling thread up in a dictionary -- and SoShape::shapeVertex() calls it
once PER VERTEX of every generated primitive. On the a2plus assembly that pair of
__pthread_mutex_lock/unlock was 25% of a preselection ray pick (zoom-profile.py,
2026-09-15). Per-thread storage is thread local by definition; keep the pointer in one.

Appends a src/shapenodes/SoShape.cpp section to patches/coin3d.patch (git-style header like
the others, LF), generated from the pristine v4.0.3 file and verified with
tools/check-patch-applies.py."""
import io, os, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REL = 'src/shapenodes/SoShape.cpp'
PRISTINE = os.path.join(ROOT, 'scratchpad', 'coin403', REL)
WORK = os.path.join(ROOT, 'scratchpad', 'cointls-work')
P = os.path.join(ROOT, 'patches', 'coin3d.patch')

EDITS = [
    (b'static soshape_staticdata *\nsoshape_get_staticdata(void)\n{\n  return (soshape_staticdata*) soshape_staticstorage->get();\n}\n',
     b'''#ifdef __EMSCRIPTEN__
/* FCWEB: SbStorage::get() takes a mutex and looks the thread up in a dictionary on every
   call, and SoShape::shapeVertex() calls this once per vertex of every generated primitive
   -- on a large assembly that lock/unlock pair was a quarter of a preselection ray pick
   (2026-09-15). Per-thread storage is thread local by definition; cache the pointer. */
static thread_local soshape_staticdata * soshape_tls_staticdata = NULL;
#endif

static soshape_staticdata *
soshape_get_staticdata(void)
{
#ifdef __EMSCRIPTEN__
  if (!soshape_tls_staticdata) {
    soshape_tls_staticdata = (soshape_staticdata*) soshape_staticstorage->get();
  }
  return soshape_tls_staticdata;
#else
  return (soshape_staticdata*) soshape_staticstorage->get();
#endif
}
''', 1),
    (b'SoShapeP::cleanup(void)\n{\n  delete soshape_staticstorage;\n  soshape_staticstorage = NULL;\n',
     b'SoShapeP::cleanup(void)\n{\n#ifdef __EMSCRIPTEN__\n  soshape_tls_staticdata = NULL;\n#endif\n  delete soshape_staticstorage;\n  soshape_staticstorage = NULL;\n', 1),
]

src = io.open(PRISTINE, 'rb').read()
assert b'\r\n' not in src
mod = src
for old, new, n in EDITS:
    assert mod.count(old) == n, (old[:50], mod.count(old))
    mod = mod.replace(old, new)
a = os.path.join(WORK, 'a', REL); b = os.path.join(WORK, 'b', REL)
os.makedirs(os.path.dirname(a), exist_ok=True); os.makedirs(os.path.dirname(b), exist_ok=True)
io.open(a, 'wb').write(src); io.open(b, 'wb').write(mod)
r = subprocess.run(['diff', '-u', 'a/' + REL, 'b/' + REL], cwd=WORK, capture_output=True)
assert r.returncode == 1, r.stderr
body = r.stdout.split(b'\n', 2)[2]
sec = (b'diff --git a/' + REL.encode() + b' b/' + REL.encode() + b'\n--- a/' + REL.encode() + b'\n+++ b/' + REL.encode() + b'\n' + body)
raw = io.open(P, 'rb').read()
assert (b'diff --git a/' + REL.encode()) not in raw
if not raw.endswith(b'\n'):
    raw += b'\n'
io.open(P, 'wb').write(raw + sec)
io.open(os.path.join(WORK, 'sec.diff'), 'wb').write(sec)
print('appended %d bytes' % len(sec))
r = subprocess.run([sys.executable, os.path.join(ROOT, 'tools', 'check-patch-applies.py'), os.path.join(WORK, 'sec.diff'), os.path.join(WORK, 'a')], capture_output=True, text=True)
print(r.stdout.strip()[-300:], r.stderr.strip()[-300:])
sys.exit(r.returncode)
