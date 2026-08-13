// Three everyday interactions never driven by real input:
//   1. change a dimension by TYPING in the property editor
//   2. rename an object with F2 in the tree
//   3. rubber-band select in the 3D view
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
const PY = (lines) => lines.join('\n');
(async () => {
  const b = await puppeteer.launch({ executablePath: CHROME, headless: false, defaultViewport: null,
    args: ['--no-sandbox','--use-gl=angle','--use-angle=metal','--window-size=1400,900'],
    protocolTimeout: 1800000, userDataDir: '/tmp/fc-propedit' });
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
    'o = d.addObject("Part::Box","Brick"); o.Length=o.Width=o.Height=20',
    'o2 = d.addObject("Part::Box","Other"); o2.Length=o2.Width=o2.Height=10; o2.Placement.Base=App.Vector(40,0,0)',
    'd.recompute()',
    'Gui.activateWorkbench("PartWorkbench")',
    'Gui.SendMsgToActiveView("ViewAxonometric"); Gui.SendMsgToActiveView("ViewFit")',
    'Gui.Selection.clearSelection(); Gui.Selection.addSelection(o)'
  ]));
  await sl(6000);

  // ---- 1. property editor: locate the "Length" value cell and type into it
  await run(p, PY([
    'import sys',
    'from PySide6 import QtWidgets, QtCore',
    'import FreeCADGui as Gui',
    'mw = Gui.getMainWindow(); found = "none"',
    'for v in mw.findChildren(QtWidgets.QTreeView):',
    '    if not v.isVisible(): continue',
    '    m = v.model()',
    '    if m is None: continue',
    '    hits = m.match(m.index(0,0), QtCore.Qt.DisplayRole, "Length", 1, QtCore.Qt.MatchRecursive|QtCore.Qt.MatchExactly)',
    '    if hits:',
    '        idx = hits[0].sibling(hits[0].row(), 1)',
    '        v.scrollTo(idx)',
    '        r = v.visualRect(idx); g = v.viewport().mapToGlobal(r.center())',
    '        if g.x() > 0 and g.y() > 0:',
    '            found = "%d %d" % (g.x(), g.y()); break',
    'sys.__stderr__.write("PROPCELL %s\\n" % found); sys.__stderr__.flush()'
  ]));
  await sl(2500);
  const cell = /PROPCELL (\d+) (\d+)/.exec(await grab(p, 'PROPCELL'));
  if (!cell) { console.log('property editor: could not locate a Length cell -- ' + await grab(p, 'PROPCELL')); }
  else {
    await p.mouse.click(+cell[1], +cell[2]); await sl(1200);
    await p.mouse.click(+cell[1], +cell[2]); await sl(2000);   // second click starts the editor
    await p.keyboard.down(process.platform === 'darwin' ? 'Meta' : 'Control');
    await p.keyboard.press('KeyA');
    await p.keyboard.up(process.platform === 'darwin' ? 'Meta' : 'Control');
    await sl(500);
    await p.keyboard.type('42', { delay: 120 }); await sl(1200);
    await p.keyboard.press('Enter'); await sl(2500);
    await run(p, PY([
      'import sys, FreeCAD as App',
      'o = App.getDocument("PE").getObject("Brick")',
      'sys.__stderr__.write("LEN %.3f\\n" % o.Length.Value); sys.__stderr__.flush()'
    ]));
    await sl(1800);
    const len = await grab(p, 'LEN');
    console.log(`property editor typing: ${len}  ${len.includes('42.000') ? '*** the typed value applied ***' : '(expected 42.000)'}`);
  }

  // ---- 2. F2 rename in the tree
  await run(p, PY([
    'import sys',
    'from PySide6 import QtWidgets, QtCore',
    'import FreeCADGui as Gui',
    'mw = Gui.getMainWindow(); out = "none"',
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
  if (ti) {
    await p.mouse.click(+ti[1], +ti[2]); await sl(1500);
    await p.keyboard.press('F2'); await sl(2000);
    await p.keyboard.down(process.platform === 'darwin' ? 'Meta' : 'Control');
    await p.keyboard.press('KeyA');
    await p.keyboard.up(process.platform === 'darwin' ? 'Meta' : 'Control');
    await sl(400);
    await p.keyboard.type('Renamed', { delay: 110 }); await sl(1000);
    await p.keyboard.press('Enter'); await sl(2500);
    await run(p, PY([
      'import sys, FreeCAD as App',
      'o = App.getDocument("PE").getObject("Brick")',
      'sys.__stderr__.write("LABEL %r\\n" % o.Label); sys.__stderr__.flush()'
    ]));
    await sl(1800);
    const lab = await grab(p, 'LABEL');
    console.log(`F2 rename: ${lab}  ${lab.includes('Renamed') ? '*** rename applied ***' : "(still the old label)"}`);
  } else console.log('F2 rename: tree item not locatable');

  // ---- 3. rubber-band select in the 3D view (drag a box around both solids)
  await run(p, PY([
    'import sys',
    'from PySide6 import QtWidgets, QtCore',
    'import FreeCADGui as Gui',
    'Gui.Selection.clearSelection()',
    'mdi = Gui.getMainWindow().findChild(QtWidgets.QMdiArea); sub = mdi.currentSubWindow()',
    'g = sub.mapToGlobal(QtCore.QPoint(0,0))',
    'sys.__stderr__.write("SUB %d %d %d %d\\n" % (g.x(), g.y(), sub.width(), sub.height())); sys.__stderr__.flush()'
  ]));
  await sl(2200);
  const sub = /SUB (\d+) (\d+) (\d+) (\d+)/.exec(await grab(p, 'SUB'));
  if (sub) {
    const [ox, oy, w, h] = [+sub[1], +sub[2], +sub[3], +sub[4]];
    // FreeCAD's box-select needs Edit>Box selection or the shortcut; drag alone rotates.
    await run(p, 'import FreeCADGui as Gui\nGui.runCommand("Std_BoxSelection",0)\n');
    await sl(2000);
    await p.mouse.move(ox + 40, oy + 40);
    await p.mouse.down();
    for (let i = 1; i <= 8; i++) { await p.mouse.move(ox + 40 + (w-80)*i/8, oy + 40 + (h-80)*i/8); await sl(120); }
    await p.mouse.up(); await sl(3000);
    await run(p, PY([
      'import sys, FreeCADGui as Gui',
      'sys.__stderr__.write("BOXSEL %s\\n" % sorted(o.Name for o in Gui.Selection.getSelection())); sys.__stderr__.flush()'
    ]));
    await sl(1800);
    const bs = await grab(p, 'BOXSEL');
    console.log(`rubber-band select: ${bs}  ${bs.includes('Brick') && bs.includes('Other') ? '*** both solids selected ***' : ''}`);
  }
  console.log('page errors: ' + (errs.length ? errs.slice(0,3).join(' | ') : 'none'));
  await b.close().catch(()=>{}); process.exit(0);
})().catch((e)=>{console.log('DRIVER '+String(e).slice(0,200));process.exit(0);});
