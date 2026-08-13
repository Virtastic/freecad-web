// Draw a line in the Sketcher by CLICKING IN THE VIEWPORT, the way a user draws.
//
// The most intricate input path in the app: sketch edit mode + a tool state machine +
// 3D-view picking. Everything else here has been driven either from Python or through
// widget coordinates; this one goes through the viewport itself.
//
// Usage: node scratchpad/sketchdraw.js [url]
const puppeteer = require('puppeteer-core');
const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const sl = (ms) => new Promise((r) => setTimeout(r, ms));
const URL = process.argv[2] || 'http://localhost:8792/index.html';

const run = (p, code) => p.evaluate((c) => {
  const m = window.fcInstance;
  const n = new TextEncoder().encode(c).length + 1; const q = m._malloc(n); m.stringToUTF8(c, q, n);
  (window.fcRunPy || ((mm, pp) => { mm._fcweb_run_python(pp); mm._free(pp); }))(m, q);
}, code);
const readLog = (p) => p.evaluate(() => document.getElementById('log').textContent);
const last = async (p, re) => { const m = (await readLog(p)).match(re) || []; return m.length ? m[m.length - 1] : ''; };

(async () => {
  const b = await puppeteer.launch({ executablePath: CHROME, headless: false, defaultViewport: null,
    args: ['--no-sandbox', '--use-gl=angle', '--use-angle=metal', '--window-size=1400,900'],
    protocolTimeout: 1200000, userDataDir: '/tmp/fc-sketch2' });
  const p = (await b.pages())[0];
  const errs = [];
  p.on('pageerror', (e) => errs.push(String(e).slice(0, 140)));
  await p.goto(URL, { waitUntil: 'domcontentloaded', timeout: 300000 });
  const t0 = Date.now();
  while (Date.now() - t0 < 300000) {
    if (await p.evaluate(() => !!(window.fcInstance && window.fcInstance._malloc))) break;
    await sl(1000);
  }
  for (let i = 0; i < 40; i++) {
    await sl(3000);
    await run(p, 'import sys, FreeCAD\nsys.__stderr__.write("RDY %d\\n" % len(FreeCAD.__unit_test__))\nsys.__stderr__.flush()\n');
    await sl(1200);
    const m = [...(await readLog(p)).matchAll(/RDY (\d+)/g)].pop();
    if (m && +m[1] > 0) break;
  }

  // setup only: a sketch on XY, open for editing, viewport fitted
  await run(p, `
import sys
import FreeCAD as App, FreeCADGui as Gui, Sketcher
d = App.newDocument("Draw")
Gui.activateWorkbench("SketcherWorkbench")
sk = d.addObject("Sketcher::SketchObject", "Sketch")
# Seed one segment BEFORE fitting: ViewFit on an empty sketch leaves a degenerate camera
# with no extent, and then every screen point unprojects to the origin -- which is exactly
# how a working tool produces a zero-length line at (0,0) and looks broken.
import Part
sk.addGeometry(Part.LineSegment(App.Vector(-30,-30,0), App.Vector(30,-30,0)), True)
d.recompute()
Gui.activeDocument().setEdit(sk.Name, 0)
Gui.SendMsgToActiveView("ViewFit")
sys.__stderr__.write("EDIT inedit=%s geo=%d\\n" % (
    Gui.activeDocument().getInEdit() is not None, sk.GeometryCount)); sys.__stderr__.flush()
`);
  await sl(6000);
  console.log((await last(p, /EDIT [^\n]*/g)) || 'no edit line');

  // the 3D view's on-screen rectangle
  await run(p, `
import sys
from PySide6 import QtWidgets, QtCore
import FreeCADGui as Gui
mdi = Gui.getMainWindow().findChild(QtWidgets.QMdiArea)
sub = mdi.currentSubWindow() if mdi else None
if sub is None:
    sys.__stderr__.write("VP none\\n")
else:
    c = sub.mapToGlobal(QtCore.QPoint(sub.width()//2, sub.height()//2))
    sys.__stderr__.write("VP %d %d %d %d\\n" % (c.x(), c.y(), sub.width(), sub.height()))
sys.__stderr__.flush()
`);
  await sl(2000);
  const vp = /VP (\d+) (\d+) (\d+) (\d+)/.exec(await last(p, /VP [^\n]*/g));
  if (!vp) { console.log('INCONCLUSIVE: no 3D view'); await b.close(); process.exit(0); }
  const [cx, cy] = [+vp[1], +vp[2]];

  // activate the Line tool the way the toolbar does
  await run(p, 'import sys, FreeCADGui as Gui\nGui.runCommand("Sketcher_CreateLine", 0)\n'
    + 'sys.__stderr__.write("TOOL line\\n"); sys.__stderr__.flush()\n');
  await sl(3000);

  // two clicks in the viewport = one line. Move first so the tool sees hover positions.
  await p.mouse.move(cx - 120, cy - 60); await sl(700);
  await p.mouse.click(cx - 120, cy - 60); await sl(1500);
  await p.mouse.move(cx + 120, cy + 60); await sl(700);
  await p.mouse.click(cx + 120, cy + 60); await sl(2000);
  await p.keyboard.press('Escape');   // leave the tool (the Escape fix also covers this)
  await sl(2000);

  await run(p, `
import sys
import FreeCAD as App
sk = App.getDocument("Draw").getObject("Sketch")
sys.__stderr__.write("GEO count=%d\\n" % sk.GeometryCount)
for i, g in enumerate(sk.Geometry[:3]):
    try:
        sys.__stderr__.write("  g%d %s (%.1f,%.1f)->(%.1f,%.1f)\\n" % (
            i, type(g).__name__, g.StartPoint.x, g.StartPoint.y, g.EndPoint.x, g.EndPoint.y))
    except Exception:
        sys.__stderr__.write("  g%d %s\\n" % (i, type(g).__name__))
sys.__stderr__.flush()
`);
  await sl(2500);
  const log = await readLog(p);
  for (const l of (log.match(/GEO [^\n]*/g) || []).slice(-1)) console.log(l);
  for (const l of (log.match(/ {2}g\d [^\n]*/g) || []).slice(-3)) console.log(l);
  console.log('page errors: ' + (errs.length ? errs.slice(0, 3).join(' | ') : 'none'));
  await p.screenshot({ path: '/tmp/sketchdraw.png' }).catch(() => {});
  await b.close().catch(() => {}); process.exit(0);
})().catch((e) => { console.log('DRIVER ' + String(e).slice(0, 200)); process.exit(0); });
