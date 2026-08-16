// The real dimensioning workflow: activate the Dimension tool from its toolbar group,
// click the edge in the viewport, place the dimension, then deal with the value dialog.
// Aimed with view.getPointOnScreen (bottom-left origin -> flip Y against the subwindow).
const puppeteer = require('puppeteer-core');
const CHROME = process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';  // set CHROME_PATH to run off macOS
const sl = (ms) => new Promise((r) => setTimeout(r, ms));
const MOD = process.platform === 'darwin' ? 'Meta' : 'Control';
const run = (p, c) => p.evaluate((code) => {
  const m = window.fcInstance;
  const n = new TextEncoder().encode(code).length + 1; const q = m._malloc(n); m.stringToUTF8(code, q, n);
  (window.fcRunPy || ((mm, pp) => { mm._fcweb_run_python(pp); mm._free(pp); }))(m, q);
}, c);
const readLog = (p) => p.evaluate(() => document.getElementById('log').textContent);
const grab = async (p, k) => { const m = (await readLog(p)).match(new RegExp(k + ' [^\\n]*', 'g')) || []; return m.length ? m[m.length-1] : '(none)'; };
const PY = (l) => l.join('\n');
(async () => {
  const b = await puppeteer.launch({ executablePath: CHROME, headless: false, defaultViewport: null,
    args: ['--no-sandbox','--use-gl=angle','--use-angle=metal','--window-size=1400,900'],
    protocolTimeout: 900000, userDataDir: '/tmp/fc-sketchdim4' });
  const p = (await b.pages())[0];
  const errs = []; p.on('pageerror', (e) => errs.push(String(e).split('\n')[0].slice(0,140)));
  await p.goto(process.argv[2] || 'http://localhost:8792/index.html', { waitUntil: 'domcontentloaded', timeout: 300000 });
  const t0 = Date.now();
  while (Date.now() - t0 < 300000) { if (await p.evaluate(() => !!(window.fcInstance && window.fcInstance._malloc))) break; await sl(1000); }
  for (let i=0;i<40;i++){ await sl(3000); await run(p,'import sys,FreeCAD\nsys.__stderr__.write("RDY %d\\n"%len(FreeCAD.__unit_test__))\nsys.__stderr__.flush()\n'); await sl(1200);
    const m=[...(await readLog(p)).matchAll(/RDY (\d+)/g)].pop(); if(m&&+m[1]>0) break; }

  await run(p, PY([
    'import sys',
    'import FreeCAD as App, FreeCADGui as Gui, Part',
    'd = App.newDocument("SD3")',
    'sk = d.addObject("Sketcher::SketchObject","Sketch")',
    'sk.addGeometry(Part.LineSegment(App.Vector(0,0,0), App.Vector(30,0,0)), False)',
    'd.recompute()',
    'Gui.activateWorkbench("SketcherWorkbench")',
    'Gui.ActiveDocument.setEdit(sk)',
    'Gui.SendMsgToActiveView("ViewFit")',
    'sys.__stderr__.write("SETUP len=%.3f\\n" % sk.Geometry[0].length()); sys.__stderr__.flush()'
  ]));
  await sl(9000);
  console.log(await grab(p, 'SETUP'));

  // where the line's midpoint and a placement point land on screen
  await run(p, PY([
    'import sys',
    'from PySide6 import QtWidgets, QtCore',
    'import FreeCADGui as Gui',
    'v = Gui.ActiveDocument.ActiveView',
    'mid = v.getPointOnScreen(15.0, 0.0, 0.0)',
    'place = v.getPointOnScreen(15.0, -12.0, 0.0)',
    'mdi = Gui.getMainWindow().findChild(QtWidgets.QMdiArea); sub = mdi.currentSubWindow()',
    'o = sub.mapToGlobal(QtCore.QPoint(0,0))',
    'sys.__stderr__.write("PTS %d %d %d %d SUB %d %d %d\\n" % (mid[0], mid[1], place[0], place[1], o.x(), o.y(), sub.height()))',
    'sys.__stderr__.flush()'
  ]));
  await sl(3000);
  const pts = /PTS (-?\d+) (-?\d+) (-?\d+) (-?\d+) SUB (\d+) (\d+) (\d+)/.exec((await grab(p, 'PTS')).replace(/\.\d+/g, ''));
  if (!pts) { console.log('could not project: ' + await grab(p, 'PTS')); await b.close(); process.exit(0); }
  const [ox, oy, sh] = [+pts[5], +pts[6], +pts[7]];
  const EDGE = { x: ox + +pts[1], y: oy + (sh - +pts[2]) };
  const PLACE = { x: ox + +pts[3], y: oy + (sh - +pts[4]) };
  console.log(`edge at ${EDGE.x},${EDGE.y}  placement at ${PLACE.x},${PLACE.y}`);

  // activate the Dimension tool: click its toolbar group button (its default action)
  await run(p, PY([
    'import sys',
    'from PySide6 import QtWidgets',
    'import FreeCADGui as Gui',
    'mw = Gui.getMainWindow(); out="none"',
    'for tb in mw.findChildren(QtWidgets.QToolBar):',
    '    if not tb.isVisible(): continue',
    '    for a in tb.actions():',
    '        if a.objectName() == "Sketcher_CompDimensionTools" and a.isVisible() and a.isEnabled():',
    '            w = tb.widgetForAction(a)',
    '            if w and w.isVisible() and out == "none":',
    '                g = w.mapToGlobal(w.rect().center()); out="%d %d"%(g.x(),g.y())',
    'sys.__stderr__.write("DIMTOOL %s\\n" % out); sys.__stderr__.flush()'
  ]));
  await sl(2500);
  const dt = /DIMTOOL (\d+) (\d+)/.exec(await grab(p, 'DIMTOOL'));
  if (!dt) { console.log('dimension tool button not found: ' + await grab(p, 'DIMTOOL')); await b.close(); process.exit(0); }
  const before = errs.length;
  await p.mouse.click(+dt[1], +dt[2]); await sl(3500);
  // the tool is now armed: click the edge, then click where the dimension goes
  await p.mouse.move(EDGE.x, EDGE.y); await sl(700);
  await p.mouse.click(EDGE.x, EDGE.y); await sl(2000);
  await p.mouse.move(PLACE.x, PLACE.y); await sl(700);
  await p.mouse.click(PLACE.x, PLACE.y); await sl(4000);

  await run(p, PY([
    'import sys',
    'from PySide6 import QtWidgets',
    'import FreeCAD as App',
    'ds = [(type(w).__name__, w.windowTitle()) for w in QtWidgets.QApplication.topLevelWidgets() if isinstance(w, QtWidgets.QDialog) and w.isVisible()]',
    'sk = App.getDocument("SD3").getObject("Sketch")',
    'sys.__stderr__.write("STATE dlg=%s cons=%d\\n" % (ds, len(sk.Constraints))); sys.__stderr__.flush()'
  ]));
  await sl(3000);
  const st = await grab(p, 'STATE');
  const ne = errs.slice(before);
  console.log(`after dimensioning: ${st}  errors=${ne.length ? ne.join(' | ') : 'none'}`);

  // Double-clicking the dimension opens the classic "Insert datum" modal -- the deepest
  // modal in the app: inside Sketcher edit mode, from a real double-click.
  await p.mouse.move(PLACE.x, PLACE.y); await sl(600);
  await p.mouse.click(PLACE.x, PLACE.y, { clickCount: 2, delay: 90 }); await sl(5000);
  await run(p, PY([
    'import sys',
    'from PySide6 import QtWidgets',
    'ds = [(type(w).__name__, w.windowTitle()) for w in QtWidgets.QApplication.topLevelWidgets() if isinstance(w, QtWidgets.QDialog) and w.isVisible()]',
    'sys.__stderr__.write("DATUM %s\\n" % ds); sys.__stderr__.flush()'
  ]));
  await sl(2500);
  const datum = await grab(p, 'DATUM');
  console.log('double-click the dimension: ' + datum + (/QDialog/.test(datum) ? '   *** the datum dialog opens ***' : '   (no dialog)'));
  if (/QDialog/.test(datum)) {
    await p.keyboard.down(MOD); await p.keyboard.press('KeyA'); await p.keyboard.up(MOD); await sl(400);
    await p.keyboard.type('45', { delay: 130 }); await sl(700);
    await p.keyboard.press('Enter'); await sl(5000);
  }

  if (/QDialog/.test(st)) {
    await p.keyboard.down(MOD); await p.keyboard.press('KeyA'); await p.keyboard.up(MOD); await sl(400);
    await p.keyboard.type('45', { delay: 130 }); await sl(800);
    await p.keyboard.press('Enter'); await sl(5000);
  } else if (/cons=[1-9]/.test(st)) {
    // FreeCAD 1.0 edits the value inline (on-view parameters) -- type it there
    await p.keyboard.down(MOD); await p.keyboard.press('KeyA'); await p.keyboard.up(MOD); await sl(300);
    await p.keyboard.type('45', { delay: 130 }); await sl(600);
    await p.keyboard.press('Enter'); await sl(4000);
  }
  await run(p, PY([
    'import sys, FreeCAD as App',
    'd = App.getDocument("SD3"); sk = d.getObject("Sketch"); d.recompute()',
    'cons = [(c.Type, c.Value) for c in sk.Constraints]',
    'sys.__stderr__.write("FINAL len=%.3f cons=%s dof=%s\\n" % (sk.Geometry[0].length(), cons, sk.solve())); sys.__stderr__.flush()'
  ]));
  await sl(3000);
  const fin = await grab(p, 'FINAL');
  console.log(`final: ${fin}`);
  console.log(`  ${/cons=\[\('Distance/.test(fin) ? '*** a dimensional constraint was created by real clicking ***' : '(no distance constraint)'}`);
  await run(p, PY([
    'import sys, FreeCADGui as Gui, FreeCAD as App',
    'Gui.ActiveDocument.resetEdit()',
    'd = App.getDocument("SD3"); d.addObject("Part::Box","Alive"); d.recompute()',
    'sys.__stderr__.write("ALIVE %s\\n" % [o.Name for o in d.Objects]); sys.__stderr__.flush()'
  ]));
  await sl(3000);
  console.log('after leaving edit mode: ' + await grab(p, 'ALIVE'));
  console.log('page errors: ' + (errs.length ? errs.slice(0,4).join(' | ') : 'none'));
  await b.close().catch(()=>{}); process.exit(0);
})().catch((e)=>{console.log('DRIVER '+String(e).slice(0,200));process.exit(0);});
