"""Pick parity: the element under the cursor at every point of a grid over the 3D view, from
real mouse moves + Gui.Selection.getPreselection(). Run on two engines and diff the outputs
-- the face/edge pick culling must give the same answers as Coin's full walk.
usage: pick-parity.py OUT.json [example=PartDesignExample] [query=?noidbfs] [cols=24] [rows=14]"""
import importlib.util, json, sys, time
from playwright.sync_api import sync_playwright
_spec = importlib.util.spec_from_file_location('ab', 'scratchpad/gpu-aa-ab.py'); ab = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(ab)
_spec2 = importlib.util.spec_from_file_location('ea', 'scratchpad/gpu-edges-ab.py'); ea = importlib.util.module_from_spec(_spec2); _spec2.loader.exec_module(ea)
OUT = sys.argv[1]
EX = sys.argv[2] if len(sys.argv) > 2 else 'PartDesignExample'
q = sys.argv[3] if len(sys.argv) > 3 else '?noidbfs'
COLS = int(sys.argv[4]) if len(sys.argv) > 4 else 24
ROWS = int(sys.argv[5]) if len(sys.argv) > 5 else 14
PRE = "\n".join([
    "import FreeCADGui, json",
    "p = FreeCADGui.Selection.getPreselection()",
    "open('/tmp/pre.txt', 'w').write(json.dumps([p.ObjectName, p.SubElementNames[0] if p.SubElementNames else '', [round(x, 3) for x in p.PickedPoints[0]] if p.PickedPoints else None] if p and p.ObjectName else None))", ""])
with sync_playwright() as pw:
    ctx = pw.chromium.launch_persistent_context('C:/Users/Michael Stavridis/AppData/Local/Temp/pickparity', channel='chrome', headless=False, device_scale_factor=1.5,
        args=['--enable-features=WebAssemblyJavaScriptPromiseIntegration', '--js-flags=--experimental-wasm-jspi', '--use-angle=d3d11', '--disable-backgrounding-occluded-windows', '--disable-renderer-backgrounding', '--disable-background-timer-throttling'], viewport={'width': 1707, 'height': 932})
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    errs = []
    page.on('console', lambda m: errs.append(m.text[:200]) if m.type == 'error' else None)
    page.on('pageerror', lambda e: errs.append('PAGEERROR ' + str(e)[:200]))
    ab.boot(page, q); time.sleep(3)
    page.evaluate(ab.DISPATCH, ea.OPEN_PY % {'sample': EX}); ab.wait_file(page, '/tmp/edges-open.json', 600); time.sleep(5)
    rect = page.evaluate('window.__fcWidgetRect')
    page.keyboard.press('Escape'); page.mouse.click(rect[0] + 20, rect[1] + rect[3] - 20); time.sleep(1.5)
    grid = []
    t0 = time.time()
    for r in range(ROWS):
        for c in range(COLS):
            x = rect[0] + int(rect[2] * (c + 0.5) / COLS); y = rect[1] + int(rect[3] * (r + 0.5) / ROWS)
            page.mouse.move(x, y); time.sleep(0.12)
            page.evaluate("() => { try { window.fcInstance.FS.unlink('/tmp/pre.txt'); } catch (e) {} }")
            page.evaluate(ab.DISPATCH, PRE); ab.wait_file(page, '/tmp/pre.txt', 20)
            grid.append([x, y, json.loads(page.evaluate("window.fcInstance.FS.readFile('/tmp/pre.txt',{encoding:'utf8'})"))])
    dt = time.time() - t0
    hits = [g for g in grid if g[2]]
    faces = sum(1 for g in hits if g[2][1].startswith('Face')); edges = sum(1 for g in hits if g[2][1].startswith('Edge')); verts = sum(1 for g in hits if g[2][1].startswith('Vertex'))
    json.dump({'example': EX, 'rect': rect, 'grid': grid, 'errors': errs}, open(OUT, 'w'))
    print('==> %s: %d points in %.1f s, %d hits (%d faces, %d edges, %d vertices), errors %d -> %s' % (EX, len(grid), dt, len(hits), faces, edges, verts, len(errs), OUT))
    ctx.close()
