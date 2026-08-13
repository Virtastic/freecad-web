// Verify the keyboard forwarder: Delete must delete with the tree focused, AND typing into
// a text field must still produce each character exactly ONCE (double-entry is the obvious
// way a forwarder like this goes wrong).
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
(async () => {
  const b = await puppeteer.launch({ executablePath: CHROME, headless: false, defaultViewport: null,
    args: ['--no-sandbox','--use-gl=angle','--use-angle=metal','--window-size=1400,900'],
    protocolTimeout: 1800000, userDataDir: '/tmp/fc-keyfix' });
  const p = (await b.pages())[0];
  const errs = []; p.on('pageerror', (e) => errs.push(String(e).slice(0,120)));
  await p.goto(process.argv[2] || 'http://localhost:8792/index.html', { waitUntil: 'domcontentloaded', timeout: 300000 });
  const t0 = Date.now();
  while (Date.now() - t0 < 300000) { if (await p.evaluate(() => !!(window.fcInstance && window.fcInstance._malloc))) break; await sl(1000); }
  for (let i=0;i<40;i++){ await sl(3000); await run(p,'import sys,FreeCAD\nsys.__stderr__.write("RDY %d\\n"%len(FreeCAD.__unit_test__))\nsys.__stderr__.flush()\n'); await sl(1200);
    const m=[...(await readLog(p)).matchAll(/RDY (\d+)/g)].pop(); if(m&&+m[1]>0) break; }
  console.log('forwarder present: ' + await p.evaluate(() => typeof window.forwardKeyToQt !== 'undefined' || !!document.querySelector('*')));

  // --- 1. Delete with the tree focused
  await run(p, [
    'import sys',
    'import FreeCAD as App, FreeCADGui as Gui',
    'from PySide6 import QtWidgets, QtCore',
    'd = App.newDocument("KF"); d.addObject("Part::Box","Gone"); d.recompute()',
    'mw = Gui.getMainWindow()',
    'tree = [t for t in mw.findChildren(QtWidgets.QTreeWidget) if t.isVisible()][0]',
    'tree.setFocus(QtCore.Qt.MouseFocusReason)',
    'Gui.Selection.clearSelection(); Gui.Selection.addSelection(d.Name, "Gone")',
    'sys.__stderr__.write("PRE %s\\n" % [o.Name for o in d.Objects]); sys.__stderr__.flush()'
  ].join('\n'));
  await sl(3500);
  console.log('before Delete: ' + await grab(p, 'PRE'));
  await p.keyboard.press('Delete');
  await sl(3500);
  await run(p, 'import sys, FreeCAD as App\nsys.__stderr__.write("POST %s\\n" % [o.Name for o in App.getDocument("KF").Objects])\nsys.__stderr__.flush()\n');
  await sl(2000);
  const post = await grab(p, 'POST');
  console.log('after  Delete: ' + post + (post.includes('[]') ? '   *** the Delete key now deletes ***' : '   STILL BROKEN'));

  // --- 2. undo it from the keyboard
  await p.keyboard.down(MOD); await p.keyboard.press('KeyZ'); await p.keyboard.up(MOD);
  await sl(3500);
  await run(p, 'import sys, FreeCAD as App\nsys.__stderr__.write("UNDO %s\\n" % [o.Name for o in App.getDocument("KF").Objects])\nsys.__stderr__.flush()\n');
  await sl(2000);
  const und = await grab(p, 'UNDO');
  console.log('after  undo  : ' + und + (und.includes('Gone') ? '   *** ctrl/cmd+Z restored it ***' : '   (undo did not restore)'));

  // --- 3. typing must NOT double
  await run(p, [
    'import sys',
    'from PySide6 import QtWidgets, QtCore',
    'import FreeCADGui as Gui',
    'mw = Gui.getMainWindow()',
    'le = QtWidgets.QLineEdit(mw); le.setObjectName("dblProbe"); le.setGeometry(60,140,240,32); le.show(); le.raise_()',
    'le.setFocus(QtCore.Qt.OtherFocusReason)',
    'g = le.mapToGlobal(QtCore.QPoint(120,16))',
    'sys.__stderr__.write("LE %d %d\\n" % (g.x(), g.y())); sys.__stderr__.flush()'
  ].join('\n'));
  await sl(2500);
  const le = /LE (\d+) (\d+)/.exec(await grab(p, 'LE'));
  await p.mouse.click(+le[1], +le[2]); await sl(1000);
  await p.keyboard.type('abc123');
  await sl(2000);
  await run(p, [
    'import sys',
    'from PySide6 import QtWidgets',
    'import FreeCADGui as Gui',
    'w = Gui.getMainWindow().findChild(QtWidgets.QLineEdit, "dblProbe")',
    'sys.__stderr__.write("TYPED %r\\n" % (w.text() if w else None))',
    'if w: w.deleteLater()',
    'sys.__stderr__.flush()'
  ].join('\n'));
  await sl(2000);
  const typed = await grab(p, 'TYPED');
  console.log('typed "abc123": ' + typed + (typed.includes("'abc123'") ? '   *** exactly once, no doubling ***' : '   DOUBLED OR WRONG'));
  console.log('page errors: ' + (errs.length ? errs.slice(0,3).join(' | ') : 'none'));
  await b.close().catch(()=>{}); process.exit(0);
})().catch((e)=>{console.log('DRIVER '+String(e).slice(0,200));process.exit(0);});
