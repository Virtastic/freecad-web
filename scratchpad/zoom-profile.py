"""Where do the seconds go while zooming the 42 MB a2plus assembly? Wheel ticks at the view centre,
the longest gap between animation frames, and a CPU profile of the burst by function.
usage: zoom-profile.py [file|example] [query] [pw|js]"""
import importlib.util, json, sys, time
from playwright.sync_api import sync_playwright
_spec = importlib.util.spec_from_file_location('ab', 'scratchpad/gpu-aa-ab.py'); ab = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(ab)
_spec2 = importlib.util.spec_from_file_location('ea', 'scratchpad/gpu-edges-ab.py'); ea = importlib.util.module_from_spec(_spec2); _spec2.loader.exec_module(ea)
_spec3 = importlib.util.spec_from_file_location('op', 'scratchpad/gpu-open-profile.py'); op = importlib.util.module_from_spec(_spec3); _spec3.loader.exec_module(op)
FILE = sys.argv[1] if len(sys.argv) > 1 else '900a_GA3DtechProject_v1.0.FCStd'
q = sys.argv[2] if len(sys.argv) > 2 else '?noidbfs'
MODE = sys.argv[3] if len(sys.argv) > 3 else 'pw'
CAM = "\n".join([
    "import FreeCADGui",
    "s = FreeCADGui.ActiveDocument.ActiveView.getCamera()",
    "open('/tmp/cam.txt','w').write(' '.join(l.strip() for l in s.splitlines() if 'height' in l or 'position' in l))", ""])
FILT = "\n".join([
    "from PySide6 import QtCore, QtWidgets",
    "class _F(QtCore.QObject):",
    "    n = {}",
    "    def eventFilter(self, o, e):",
    "        t = e.type()",
    "        if t in (QtCore.QEvent.Type.Wheel, QtCore.QEvent.Type.MouseButtonPress):",
    "            k = str(t) + ' ' + o.metaObject().className(); self.n[k] = self.n.get(k, 0) + 1",
    "        return False",
    "app = QtWidgets.QApplication.instance(); app._zf = _F(); app.installEventFilter(app._zf)", ""])
DUMP = "\n".join([
    "import json",
    "from PySide6 import QtWidgets",
    "open('/tmp/zf.json','w').write(json.dumps(QtWidgets.QApplication.instance()._zf.n))", ""])
DEEP = "(a) => { let el = document.elementFromPoint(a[0], a[1]); while (el.shadowRoot && el.shadowRoot.elementFromPoint(a[0], a[1])) el = el.shadowRoot.elementFromPoint(a[0], a[1]); return el; }"
with sync_playwright() as pw:
    ctx = pw.chromium.launch_persistent_context('C:/Users/Michael Stavridis/AppData/Local/Temp/zoomprof', channel='chrome', headless=False, device_scale_factor=1.5,
        args=['--enable-features=WebAssemblyJavaScriptPromiseIntegration', '--js-flags=--experimental-wasm-jspi', '--use-angle=d3d11', '--disable-backgrounding-occluded-windows', '--disable-renderer-backgrounding', '--disable-background-timer-throttling'], viewport={'width': 1707, 'height': 932})
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    errs = []
    page.on('console', lambda m: errs.append(m.type + ': ' + m.text[:200]) if m.type in ('error', 'warning') else None)
    page.on('pageerror', lambda e: errs.append('PAGEERROR ' + str(e)[:200]))
    page.add_init_script(ab.BLIT_JS)
    ab.boot(page, q); time.sleep(3)
    target = FILE
    if FILE.endswith('.FCStd') and not FILE.startswith('/'):
        page.evaluate("""async (a) => { const r = await fetch(a[0]); const b = new Uint8Array(await r.arrayBuffer()); window.fcInstance.FS.writeFile(a[1], b); return b.length; }""", ['http://127.0.0.1:8099/' + FILE, '/home/web_user/' + FILE]); target = '/home/web_user/' + FILE
    t0 = time.time(); page.evaluate(ab.DISPATCH, ea.OPEN_PY % {'sample': target}); ok = ab.wait_file(page, '/tmp/edges-open.json', 300); print('==> opened in %.1f s ok=%s' % (time.time() - t0, ok), flush=True)
    if not ok:
        page.screenshot(path='scratchpad/zoom-stuck.png'); log = page.evaluate("document.getElementById('log').textContent"); print('==> LOG TAIL', log[-3000:].replace(chr(10), ' | '), flush=True)
        print('==> live', page.evaluate('JSON.stringify({live: window.fcInstance.Asyncify && window.fcInstance.Asyncify.__live, py: window.fcInstance.Asyncify && window.fcInstance.Asyncify.__pyActive, yields: window.fcInstance.__fcYields})'), flush=True)
        ctx.close(); raise SystemExit(1)
    time.sleep(8)
    rect = page.evaluate('window.__fcWidgetRect'); cx, cy = rect[0] + int(rect[2] * float(sys.argv[4] if len(sys.argv) > 4 else 0.35)), rect[1] + rect[3] // 2
    page.keyboard.press('Escape'); page.mouse.click(rect[0] + 20, rect[1] + rect[3] - 20); time.sleep(2)
    page.mouse.move(cx, cy); time.sleep(1)
    def cam(tag):
        page.evaluate("() => { try { window.fcInstance.FS.unlink('/tmp/cam.txt'); } catch (e) {} }"); page.evaluate(ab.DISPATCH, CAM); ab.wait_file(page, '/tmp/cam.txt', 30)
        print('==> cam %s: %s  drawn=%s' % (tag, page.evaluate("window.fcInstance.FS.readFile('/tmp/cam.txt',{encoding:'utf8'})"), page.evaluate('window.__fcWidgetDrawn||0')), flush=True)
    cam('before'); print('==> rect', rect, 'center', cx, cy)
    page.evaluate(ab.DISPATCH, FILT); time.sleep(1)
    page.evaluate("window.__wheelSeen = 0; window.addEventListener('wheel', () => window.__wheelSeen++, true)")
    DL = "JSON.stringify((window.fcInstance.__fcDL||{}).stats||{})"; print('==> DL before', page.evaluate(DL))
    cdp = ctx.new_cdp_session(page); cdp.send('Profiler.enable'); cdp.send('Profiler.setSamplingInterval', {'interval': 1000})
    page.evaluate("window.__gap={max:0,n:0,last:performance.now(),gaps:[]}; (function f(){const t=performance.now(); const g=window.__gap; const d=t-g.last; if(d>g.max) g.max=d; if(d>100) g.gaps.push(Math.round(d)); g.last=t; g.n++; g.raf=requestAnimationFrame(f);})()")
    b0 = page.evaluate('window.__blits||0'); cdp.send('Profiler.start'); t1 = time.time()
    def wheel(dy):
        if MODE == 'move': page.mouse.move(cx + (3 if dy < 0 else -3), cy); cx_ = cx
        elif MODE == 'still': page.mouse.wheel(0, dy)
        elif MODE == 'pw': page.mouse.move(cx + 1, cy); page.mouse.move(cx, cy); page.mouse.wheel(0, dy)
        else: page.evaluate("(a) => { const el = (" + DEEP + ")(a); el.dispatchEvent(new WheelEvent('wheel', {bubbles: true, cancelable: true, composed: true, clientX: a[0], clientY: a[1], deltaY: a[2], deltaMode: 0})); }", [cx, cy, dy])
    print('==> wheel target', page.evaluate("(a) => { const el = (" + DEEP + ")(a); return el.tagName + '#' + el.id + '.' + el.className; }", [cx, cy]), 'mode', MODE)
    N = int(sys.argv[5]) if len(sys.argv) > 5 else 6; DT = float(sys.argv[6]) if len(sys.argv) > 6 else 0.15
    if MODE == 'sweep':
        for i in range(20): page.mouse.move(cx - 150 + 15 * i, cy); time.sleep(0.05)
        time.sleep(2); cam('mid'); print('==> gaps during 20 sweep moves', page.evaluate('window.__gap.gaps.splice(0)'))
        for i in range(20): page.mouse.move(cx + 150 - 15 * i, cy + 40); time.sleep(0.05)
        time.sleep(2); print('==> gaps during 20 sweep moves back', page.evaluate('window.__gap.gaps.splice(0)'))
    elif MODE == 'zin':
        for i in range(N): page.mouse.wheel(0, -120); time.sleep(DT)
        time.sleep(2); cam('zoomed in'); print('==> gaps during zoom-in', page.evaluate('window.__gap.gaps.splice(0)'))
        for i in range(20): page.mouse.move(cx + (3 if i % 2 else -3), cy); time.sleep(0.05)
        time.sleep(2); print('==> gaps during 20 moves zoomed in', page.evaluate('window.__gap.gaps.splice(0)'))
        for i in range(N): page.mouse.wheel(0, 120); time.sleep(DT)
        time.sleep(2); cam('zoomed out'); print('==> gaps during zoom-out', page.evaluate('window.__gap.gaps.splice(0)'))
        for i in range(20): page.mouse.move(cx + (3 if i % 2 else -3), cy); time.sleep(0.05)
        time.sleep(2); print('==> gaps during 20 moves zoomed out', page.evaluate('window.__gap.gaps.splice(0)'))
    else:
        for i in range(N): wheel(-120); time.sleep(DT)
        time.sleep(1.5); cam('mid')
        for i in range(N): wheel(120); time.sleep(DT)
    time.sleep(2.5)
    page.evaluate(ab.DISPATCH, DUMP); ab.wait_file(page, '/tmp/zf.json', 30)
    print('==> qt events', page.evaluate("window.fcInstance.FS.readFile('/tmp/zf.json',{encoding:'utf8'})"), 'dom wheel seen', page.evaluate('window.__wheelSeen'), 'errors', errs[:5])
    cam('after'); print('==> DL after', page.evaluate(DL)); page.screenshot(path='scratchpad/zoom-after.png')
    prof = cdp.send('Profiler.stop')['profile']; dt = time.time() - t1
    g = page.evaluate('(cancelAnimationFrame(window.__gap.raf), window.__gap)')
    total, by_fn, by_bucket = op.aggregate(prof)
    print('==> zoom burst %.1f s: scene frames %d, rAF frames %d, longest gap %.0f ms, gaps>100ms %s' % (dt, page.evaluate('window.__blits||0') - b0, g['n'], g['max'], g['gaps']))
    for b, us in by_bucket.most_common(8): print('   %5.1f%%  %6.2fs  %s' % (100.0 * us / total, us / 1e6, b))
    print('   top functions:')
    for fn, us in by_fn.most_common(30): print('   %5.1f%%  %6.2fs  %s' % (100.0 * us / total, us / 1e6, fn[:120]))
    json.dump(prof, open('scratchpad/zoom-prof.json', 'w'))
    for needle in ('__pthread_mutex_lock', 'generatePrimitives', 'SoRayPickAction::intersect', 'shapeVertex'):
        print('   callers of', needle)
        for ch, us in op.callers(prof, needle, depth=12, top=3): print('     %6.2fs  %s' % (us / 1e6, ch))
    ctx.close()
