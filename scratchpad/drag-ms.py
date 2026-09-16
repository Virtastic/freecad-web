"""ms per scene frame for desk-bench's drag stimulus (60 camera rotations + updateGui), best of 3,
for one sample under one query string. python scratchpad/drag-ms.py SAMPLE [QUERY]"""
import importlib.util, json, sys, time
from playwright.sync_api import sync_playwright
_spec = importlib.util.spec_from_file_location('ab', 'scratchpad/gpu-aa-ab.py'); ab = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(ab)
_spec2 = importlib.util.spec_from_file_location('ea', 'scratchpad/gpu-edges-ab.py'); ea = importlib.util.module_from_spec(_spec2); _spec2.loader.exec_module(ea)
DRAG_PY = """
import FreeCAD, FreeCADGui, time, json
v = FreeCADGui.activeDocument().activeView()
v.viewAxonometric(); FreeCADGui.SendMsgToActiveView('ViewFit'); FreeCADGui.updateGui()
rot0 = v.getCameraOrientation()
best = None
for rep in range(3):
    t0 = time.time()
    for i in range(60):
        v.setCameraOrientation(FreeCAD.Rotation(FreeCAD.Vector(0, 0, 1), 1.5 * (i + 1)).multiply(rot0))
        FreeCADGui.updateGui()
    dt = time.time() - t0
    best = dt if best is None or dt < best else best
open('/tmp/drag-ms.json', 'w').write(json.dumps({'best_s': best}))
"""
def main():
    sample = sys.argv[1]; q = sys.argv[2] if len(sys.argv) > 2 else '?noidbfs'
    errs = []
    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context('C:/Users/Michael Stavridis/AppData/Local/Temp/dragms', channel='chrome', headless=False, device_scale_factor=1.5,
            args=['--enable-features=WebAssemblyJavaScriptPromiseIntegration', '--js-flags=--experimental-wasm-jspi', '--use-angle=d3d11', '--disable-backgrounding-occluded-windows', '--disable-renderer-backgrounding', '--disable-background-timer-throttling'], viewport={'width': 1707, 'height': 932})
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.on('console', lambda m: errs.append(m.text[:160]) if m.type in ('error', 'warning') else None)
        page.add_init_script(ab.BLIT_JS)
        ab.boot(page, q); time.sleep(3)
        page.evaluate(ab.DISPATCH, ea.OPEN_PY % {'sample': sample}); ab.wait_file(page, '/tmp/edges-open.json', 900); time.sleep(6)
        b0 = page.evaluate('window.__blits || 0')
        prof = None
        if len(sys.argv) > 3 and sys.argv[3] == 'profile':
            _sp = importlib.util.spec_from_file_location('op', 'scratchpad/gpu-open-profile.py'); op = importlib.util.module_from_spec(_sp); _sp.loader.exec_module(op)
            cdp = ctx.new_cdp_session(page); cdp.send('Profiler.enable'); cdp.send('Profiler.setSamplingInterval', {'interval': 500}); cdp.send('Profiler.start')
        page.evaluate(ab.DISPATCH, DRAG_PY); ab.wait_file(page, '/tmp/drag-ms.json', 600); r = json.loads(page.evaluate("window.fcInstance.FS.readFile('/tmp/drag-ms.json',{encoding:'utf8'})"))
        if len(sys.argv) > 3 and sys.argv[3] == 'profile':
            prof = cdp.send('Profiler.stop')['profile']; total, by_fn, by_bucket = op.aggregate(prof)
            for b, us in by_bucket.most_common(8): print('   %5.1f%%  %6.2fs  %s' % (100.0 * us / total, us / 1e6, b))
            for fn, us in by_fn.most_common(28): print('   %5.1f%%  %6.2fs  %s' % (100.0 * us / total, us / 1e6, fn[:110])); r = json.loads(page.evaluate("window.fcInstance.FS.readFile('/tmp/drag-ms.json',{encoding:'utf8'})"))
        frames = (page.evaluate('window.__blits || 0') - b0) / 3.0
        print('==> %-18s %-28s best %5.1f ms/rotation (%.0f frames per pass)  console err/warn %d' % (sample, q, r['best_s'] * 1000.0 / 60.0, frames, len(errs)), flush=True)
        ctx.close()
main()
