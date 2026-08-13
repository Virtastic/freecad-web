// Property-editor typing and F2 rename, with the Model panel actually raised first.
const puppeteer = require('puppeteer-core');
const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
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
    protocolTimeout: 1800000, userDataDir: '/tmp/fc-propedit2' });
  const p = (await b.pages())[0];
  const errs = []; p.on('pageerror', (e) => errs.push(String(e).slice(0,120)));
  await p.goto(process.argv[2] || 'http://localhost:8792/index.html', { waitUntil: 'domcontentloaded', timeout: 300000 });
  const t0 = Date.now();
  while (Date.now() - t0 < 300000) { if (await p.evaluate(() => !!(window.fcInstance && window.fcInstance._malloc))) break; await sl(1000); }
  for (let i=0;i<40;i++){ await sl(3000); await run(p,'import sys,FreeCAD\nsys.__stderr__.write("RDY %d\\n"%len(FreeCAD.__unit_test__))\nsys.__stderr__.flush()\n'); await sl(1200);
    const m=[...(await readLog(p)).matchAll(/RDY (\d+)/g)].pop(); if(m&&+m[1]>0) break; }

  await run(p, PY([
    'import FreeCAD as App, FreeCADGui as Gui',
    'd = App.newDocument("PE")',
    'o = d.addObject("Part::Box","Brick"); o.Length=o.Width=o.Height=20; d.recompute()',
    'Gui.activateWorkbench("PartWorkbench")',
    'Gui.SendMsgToActiveView("ViewAxonometric"); Gui.SendMsgToActiveView("ViewFit")'
  ]));
  await sl(5000);
  // raise the Model dock (combo view) the way a user would: click its tab
  await run(p, PY([
    'import sys',
    'from PySide6 import QtWidgets',
    'import FreeCADGui as Gui',
    'mw = Gui.getMainWindow()',
    'for dw in mw.findChildren(QtWidgets.QDockWidget):',
    '    if "model" in dw.windowTitle().strip().lower(): dw.show(); dw.raise_()',
    'for tb in mw.findChildren(QtWidgets.QTabBar):',
    '    for i in range(tb.count()):',
    '        if tb.tabText(i).strip().lower()=="model":',
    '            g = tb.mapToGlobal(tb.tabRect(i).center()); sys.__stderr__.write("MTAB %d %d\\n"%(g.x(),g.y()))',
    'sys.__stderr__.flush()'
  ]));
  await sl(2500);
  const mt = /MTAB (\d+) (\d+)/.exec(await grab(p, 'MTAB'));
  if (mt) { await p.mouse.click(+mt[1], +mt[2]); await sl(2500); }

  // select the box via the tree so the property editor fills, and report what IS visible
  await run(p, PY([
    'import sys',
    'from PySide6 import QtWidgets, QtCore',
    'import FreeCAD as App, FreeCADGui as Gui',
    'Gui.Selection.clearSelection(); Gui.Selection.addSelection(App.getDocument("PE").getObject("Brick"))',
    'mw = Gui.getMainWindow()',
    'vis = [type(v).__name__ for v in mw.findChildren(QtWidgets.QAbstractItemView) if v.isVisible()]',
    'sys.__stderr__.write("VIEWS %s\\n" % vis); sys.__stderr__.flush()'
  ]));
  await sl(3000);
  console.log(await grab(p, 'VIEWS'));

  await run(p, PY([
    'import sys',
    'from PySide6 import QtWidgets, QtCore',
    'import FreeCADGui as Gui',
    'mw = Gui.getMainWindow(); found="none"',
    'for v in mw.findChildren(QtWidgets.QAbstractItemView):',
    '    if not v.isVisible(): continue',
    '    m = v.model()',
    '    if m is None: continue',
    '    hits = m.match(m.index(0,0), QtCore.Qt.DisplayRole, "Length", 2, QtCore.Qt.MatchRecursive|QtCore.Qt.MatchExactly)',
    '    for h in hits:',
    '        idx = h.sibling(h.row(), 1)',
    '        v.scrollTo(idx); r = v.visualRect(idx)',
    '        if r.isEmpty(): continue',
    '        g = v.viewport().mapToGlobal(r.center())',
    '        if g.x()>0 and g.y()>0: found = "%d %d" % (g.x(), g.y()); break',
    '    if found!="none": break',
    'sys.__stderr__.write("PROPCELL %s\\n" % found); sys.__stderr__.flush()'
  ]));
  await sl(2500);
  const cell = /PROPCELL (\d+) (\d+)/.exec(await grab(p, 'PROPCELL'));
  if (!cell) console.log('property editor: still no Length cell -- ' + await grab(p, 'PROPCELL'));
  else {
    await p.mouse.click(+cell[1], +cell[2]); await sl(1200);
    await p.mouse.click(+cell[1], +cell[2]); await sl(2200);
    await p.keyboard.down(MOD); await p.keyboard.press('KeyA'); await p.keyboard.up(MOD); await sl(500);
    await p.keyboard.type('42', { delay: 130 }); await sl(1200);
    await p.keyboard.press('Enter'); await sl(3000);
    await run(p, 'import sys, FreeCAD as App\nsys.__stderr__.write("LEN %.3f\\n" % App.getDocument("PE").getObject("Brick").Length.Value)\nsys.__stderr__.flush()\n');
    await sl(1800);
    const len = await grab(p, 'LEN');
    console.log(`property editor typing: ${len}  ${len.includes('42.000') ? '*** typed value applied ***' : '(expected 42.000)'}`);
  }

  await run(p, PY([
    'import sys',
    'from PySide6 import QtWidgets, QtCore',
    'import FreeCADGui as Gui',
    'mw = Gui.getMainWindow(); out="none"',
    'for t in mw.findChildren(QtWidgets.QTreeWidget):',
    '    if not t.isVisible(): continue',
    '    m = t.model()',
    '    r = m.match(m.index(0,0), QtCore.Qt.DisplayRole, "Brick", 1, QtCore.Qt.MatchRecursive|QtCore.Qt.MatchExactly)',
    '    if r:',
    '        t.scrollTo(r[0]); g = t.viewport().mapToGlobal(t.visualRect(r[0]).center())',
    '        if g.x()>0 and g.y()>0: out = "%d %d" % (g.x(), g.y()); break',
    'sys.__stderr__.write("TREEITEM %s\\n" % out); sys.__stderr__.flush()'
  ]));
  await sl(2500);
  const ti = /TREEITEM (\d+) (\d+)/.exec(await grab(p, 'TREEITEM'));
  if (!ti) console.log('F2 rename: tree item still not locatable -- ' + await grab(p, 'TREEITEM'));
  else {
    await p.mouse.click(+ti[1], +ti[2]); await sl(1500);
    await p.keyboard.press('F2'); await sl(2200);
    await p.keyboard.down(MOD); await p.keyboard.press('KeyA'); await p.keyboard.up(MOD); await sl(400);
    await p.keyboard.type('Renamed', { delay: 110 }); await sl(1000);
    await p.keyboard.press('Enter'); await sl(2500);
    await run(p, 'import sys, FreeCAD as App\nsys.__stderr__.write("LABEL %r\\n" % App.getDocument("PE").getObject("Brick").Label)\nsys.__stderr__.flush()\n');
    await sl(1800);
    const lab = await grab(p, 'LABEL');
    console.log(`F2 rename: ${lab}  ${lab.includes('Renamed') ? '*** rename applied ***' : '(label unchanged)'}`);
  }
  console.log('page errors: ' + (errs.length ? errs.slice(0,3).join(' | ') : 'none'));
  await b.close().catch(()=>{}); process.exit(0);
})().catch((e)=>{console.log('DRIVER '+String(e).slice(0,200));process.exit(0);});
