// Two more everyday interactions never verified: mouse WHEEL zoom in the 3D view, and
// DOUBLE-CLICK on a tree item to open its editor. Keys turned out to be dropped entirely
// when focus was not in a text field, so other event classes deserve the same scrutiny.
// Assert on the camera actually moving / an editor actually opening, never on "handled".
const puppeteer = require('puppeteer-core');
const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const sl = (ms) => new Promise((r) => setTimeout(r, ms));
const run = (p, c) => p.evaluate((code) => {
  const m = window.fcInstance;
  const n = new TextEncoder().encode(code).length + 1; const q = m._malloc(n); m.stringToUTF8(code, q, n);
  (window.fcRunPy || ((mm, pp) => { mm._fcweb_run_python(pp); mm._free(pp); }))(m, q);
}, c);
const readLog = (p) => p.evaluate(() => document.getElementById('log').textContent);
const grab = async (p, k) => { const m = (await readLog(p)).match(new RegExp(k + ' [^\\n]*', 'g')) || []; return m.length ? m[m.length-1] : '(none)'; };
(async () => {
  const b = await puppeteer.launch({ executablePath: CHROME, headless: false, defaultViewport: null,
    args: ['--no-sandbox','--use-gl=angle','--use-angle=metal','--window-size=1400,900'],
    protocolTimeout: 1800000, userDataDir: '/tmp/fc-wheel' });
  const p = (await b.pages())[0];
  const errs = []; p.on('pageerror', (e) => errs.push(String(e).slice(0,120)));
  await p.goto(process.argv[2] || 'http://localhost:8792/index.html', { waitUntil: 'domcontentloaded', timeout: 300000 });
  const t0 = Date.now();
  while (Date.now() - t0 < 300000) { if (await p.evaluate(() => !!(window.fcInstance && window.fcInstance._malloc))) break; await sl(1000); }
  for (let i=0;i<40;i++){ await sl(3000); await run(p,'import sys,FreeCAD\nsys.__stderr__.write("RDY %d\\n"%len(FreeCAD.__unit_test__))\nsys.__stderr__.flush()\n'); await sl(1200);
    const m=[...(await readLog(p)).matchAll(/RDY (\d+)/g)].pop(); if(m&&+m[1]>0) break; }

  await run(p, [
    'import sys',
    'import FreeCAD as App, FreeCADGui as Gui',
    'from PySide6 import QtWidgets, QtCore',
    'd = App.newDocument("WD")',
    'd.addObject("Part::Box","Cube"); d.recompute()',
    'Gui.activateWorkbench("PartWorkbench")',
    'Gui.SendMsgToActiveView("ViewFit")',
    'mdi = Gui.getMainWindow().findChild(QtWidgets.QMdiArea)',
    'sub = mdi.currentSubWindow()',
    'c = sub.mapToGlobal(QtCore.QPoint(sub.width()//2, sub.height()//2))',
    'sys.__stderr__.write("VIEW %d %d\\n" % (c.x(), c.y()))',
    'sys.__stderr__.flush()'
  ].join('\n'));
  await sl(5000);
  const vw = /VIEW (\d+) (\d+)/.exec(await grab(p, 'VIEW'));

  const camHeight = async (tag) => {
    await run(p, [
      'import sys, re',
      'import FreeCADGui as Gui',
      'cam = Gui.activeDocument().activeView().getCamera()',
      'm = re.search(r"height\\s+([0-9.eE+-]+)", cam)',
      'sys.__stderr__.write("CAM ' + tag + ' %s\\n" % (m.group(1) if m else "?"))',
      'sys.__stderr__.flush()'
    ].join('\n'));
    await sl(1800);
    return (await grab(p, 'CAM ' + tag)).replace('CAM ' + tag + ' ', '');
  };

  const h0 = await camHeight('A');
  await p.mouse.move(+vw[1], +vw[2]); await sl(600);
  for (let i = 0; i < 5; i++) { await p.mouse.wheel({ deltaY: -240 }); await sl(400); }
  await sl(2000);
  const h1 = await camHeight('B');
  console.log(`wheel zoom: camera height ${h0} -> ${h1}  ${h0 !== h1 && h1 !== '?' ? '*** the wheel zooms ***' : 'NO CHANGE -- wheel does nothing'}`);

  // double-click a tree item: should open the object's editor / task panel
  await run(p, [
    'import sys',
    'from PySide6 import QtWidgets, QtCore',
    'import FreeCADGui as Gui',
    'mw = Gui.getMainWindow()',
    'for tb in mw.findChildren(QtWidgets.QTabBar):',
    '    for i in range(tb.count()):',
    '        if tb.tabText(i).strip().lower() == "model":',
    '            g = tb.mapToGlobal(tb.tabRect(i).center()); sys.__stderr__.write("TAB %d %d\\n" % (g.x(), g.y()))',
    'sys.__stderr__.flush()'
  ].join('\n'));
  await sl(2000);
  const tab = /TAB (\d+) (\d+)/.exec(await grab(p, 'TAB'));
  if (tab) { await p.mouse.click(+tab[1], +tab[2]); await sl(2000); }
  await run(p, [
    'import sys',
    'from PySide6 import QtWidgets, QtCore',
    'import FreeCADGui as Gui',
    'mw = Gui.getMainWindow(); hit=None',
    'for t in mw.findChildren(QtWidgets.QTreeWidget):',
    '    if not t.isVisible(): continue',
    '    m = t.model()',
    '    r = m.match(m.index(0,0), QtCore.Qt.DisplayRole, "Cube", 1, QtCore.Qt.MatchRecursive|QtCore.Qt.MatchExactly)',
    '    if r:',
    '        t.scrollTo(r[0]); g = t.viewport().mapToGlobal(t.visualRect(r[0]).center())',
    '        if g.x()>0 and g.y()>0: hit=(g.x(),g.y()); break',
    'sys.__stderr__.write("HIT %s\\n" % ("%d %d" % hit if hit else "none")); sys.__stderr__.flush()'
  ].join('\n'));
  await sl(2000);
  const hit = /HIT (\d+) (\d+)/.exec(await grab(p, 'HIT'));
  if (hit) {
    await p.mouse.click(+hit[1], +hit[2], { clickCount: 2 });
    await sl(4000);
    await run(p, [
      'import sys',
      'from PySide6 import QtWidgets',
      'import FreeCADGui as Gui',
      'mw = Gui.getMainWindow()',
      'dlg = Gui.Control.activeDialog()',
      'edits = [w for w in mw.findChildren(QtWidgets.QAbstractSpinBox) if w.isVisible()]',
      'sys.__stderr__.write("DBL taskdialog=%s visible_spinboxes=%d\\n" % (dlg is not None, len(edits)))',
      'sys.__stderr__.flush()'
    ].join('\n'));
    await sl(2500);
    const dbl = await grab(p, 'DBL');
    console.log('double-click tree item: ' + dbl + (dbl.includes('taskdialog=True') || /visible_spinboxes=[1-9]/.test(dbl) ? '   *** an editor opened ***' : '   nothing opened'));
  }
  console.log('page errors: ' + (errs.length ? errs.slice(0,3).join(' | ') : 'none'));
  await b.close().catch(()=>{}); process.exit(0);
})().catch((e)=>{console.log('DRIVER '+String(e).slice(0,200));process.exit(0);});
