"""Does the tab stay alive during a big open? Count presented frames and yields while the a2plus file loads,
and how long the longest gap between animation frames is (the freeze). Then boolean+mesh, then open again."""
import importlib.util, sys, time, json
from playwright.sync_api import sync_playwright
_spec = importlib.util.spec_from_file_location('ab', 'scratchpad/gpu-aa-ab.py'); ab = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(ab)
_spec2 = importlib.util.spec_from_file_location('ea', 'scratchpad/gpu-edges-ab.py'); ea = importlib.util.module_from_spec(_spec2); _spec2.loader.exec_module(ea)
q = sys.argv[1] if len(sys.argv) > 1 else '?noidbfs'
errs = []
with sync_playwright() as pw:
    ctx = pw.chromium.launch_persistent_context('C:/Users/Michael Stavridis/AppData/Local/Temp/yieldprobe', channel='chrome', headless=False, args=['--enable-features=WebAssemblyJavaScriptPromiseIntegration', '--js-flags=--experimental-wasm-jspi', '--use-angle=d3d11', '--disable-backgrounding-occluded-windows', '--disable-renderer-backgrounding', '--disable-background-timer-throttling'], viewport={'width': 1400, 'height': 900})
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.on('console', lambda m: errs.append(m.text[:200]) if m.type == 'error' else None)
    page.on('pageerror', lambda e: errs.append('PAGEERROR ' + str(e)[:100] + ' :: ' + ' < '.join(l.strip().replace('at FreeCAD.wasm.','').split(' (')[0][:80] for l in str(getattr(e, 'stack', '') or '').split(chr(10))[1:22])))
    ab.boot(page, q); time.sleep(3)
    page.evaluate("""async (a) => { const r = await fetch(a[0]); const b = new Uint8Array(await r.arrayBuffer()); window.fcInstance.FS.writeFile(a[1], b); return b.length; }""", ['http://127.0.0.1:8099/900a_GA3DtechProject_v1.0.FCStd', '/home/web_user/900a.FCStd'])
    page.evaluate("""() => { const c = window.fcInstance.qtSuspendResumeControl; const A = c.pendingEvents; window.__spl = []; const os = A.splice;
      A.splice = function () { const st = String(new Error().stack).split(String.fromCharCode(10)).slice(2, 40).map(l => l.trim().replace('at FreeCAD.wasm.', '').split(' (')[0]).filter(l => /fcweb_run_python|QGuiApplication::exec|qtSendPendingEvents|fcweb_dispatch_event|sendPendingEvents|processEvents|exec\(|Restore|updateGui|maybe_yield|yield_point/.test(l)).slice(0, 8).join(' < ');
        window.__spl.push([performance.now() | 0, A.length, arguments[0], window.fcInstance.__fcYields | 0, st]); if (window.__spl.length > 60) window.__spl.shift(); return os.apply(this, arguments); }; }""")
    def timed_open(tag, target):
        page.evaluate("window.__gap={max:0,n:0,last:performance.now()}; window.__gapT=(function f(){const t=performance.now(); const g=window.__gap; if(t-g.last>g.max) g.max=t-g.last; g.last=t; g.n++; g.raf=requestAnimationFrame(f);})()")
        y0 = page.evaluate('window.fcInstance.__fcYields|0'); p0 = page.evaluate('window.__fcPresented|0'); t0 = time.time()
        page.evaluate(ab.DISPATCH, ea.OPEN_PY % {'sample': target}); ab.wait_file(page, '/tmp/edges-open.json', 900)
        dt = time.time() - t0
        g = page.evaluate('(cancelAnimationFrame(window.__gap.raf), window.__gap)')
        print('==> %-8s open %5.1f s   yields %4d   frames during load %4d   longest gap %6.0f ms   errors so far %d' % (tag, dt, page.evaluate('window.fcInstance.__fcYields|0') - y0, g['n'], g['max'], len(errs)), flush=True)
        page.evaluate("() => { try { window.fcInstance.FS.unlink('/tmp/edges-open.json'); } catch (e) {} }")
    timed_open('a2plus', '/home/web_user/900a.FCStd')
    page.evaluate(ab.DISPATCH, "import FreeCAD, Part, MeshPart\nd=FreeCAD.newDocument('t')\nb=Part.makeBox(10,10,10).fuse(Part.makeSphere(6,FreeCAD.Vector(10,10,10))).cut(Part.makeCylinder(2,30))\nm=MeshPart.meshFromShape(Shape=b, LinearDeflection=0.05, AngularDeflection=0.3)\nopen('/tmp/bm.json','w').write('{\"tris\": %d}' % m.CountFacets)\n"); ok = ab.wait_file(page, '/tmp/bm.json', 300)
    print('==> boolean+mesh: %s' % (page.evaluate("window.fcInstance.FS.readFile('/tmp/bm.json',{encoding:'utf8'})") if ok else 'TIMED OUT'), flush=True)
    timed_open('BIM', 'BIMExample')
    P = page.evaluate("(()=>{const P=window.fcInstance.__fcPThread(); return {unused:P.unusedWorkers.length, pthreads:Object.keys(P.pthreads).length}})()")
    print('==> waitflag', page.evaluate('JSON.stringify(window.__fcW||null)'))
    print('==> pthreads %s   console errors %d   woken by event %s' % (P, len(errs), page.evaluate('window.fcInstance.__fcParkWokeByEvent|0')), flush=True)
    print('    first free-park stack:', (page.evaluate('window.fcInstance.__fcParkFreeStack||""') or '')[:1500], flush=True)
    for e in errs[:3]: print('    ' + e[:600], flush=True)
    for s in page.evaluate('window.__spl || []')[-14:]: print('    splice', s, flush=True)
    print('    assert lines:', page.evaluate("[...(window.__GATE||[]), ...document.getElementById('log').textContent.split(String.fromCharCode(10))].filter(l=>/ssert|emval|handle/i.test(l)).slice(0,6).join(' || ')")[:1200], flush=True)
    ctx.close()
