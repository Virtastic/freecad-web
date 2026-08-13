// Does a real Delete / Cmd+C+V reach the tree and act on the selection?
// Selection and focus are set through the API so the ONLY thing under test is the key.
const puppeteer = require('puppeteer-core');
const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const sl = (ms) => new Promise((r) => setTimeout(r, ms));
const URL = process.argv[2] || 'http://localhost:8792/index.html';
const MOD = process.platform === 'darwin' ? 'Meta' : 'Control';
const run = (p, c) => p.evaluate((code) => {
  const m = window.fcInstance;
  const n = new TextEncoder().encode(code).length + 1; const q = m._malloc(n); m.stringToUTF8(code, q, n);
  (window.fcRunPy || ((mm, pp) => { mm._fcweb_run_python(pp); mm._free(pp); }))(m, q);
}, c);
const readLog = (p) => p.evaluate(() => document.getElementById('log').textContent);
const grab = async (p, key) => { const m = (await readLog(p)).match(new RegExp(key + ' [^\\n]*', 'g')) || []; return m.length ? m[m.length-1] : '(none)'; };
(async () => {
  const b = await puppeteer.launch({ executablePath: CHROME, headless: false, defaultViewport: null,
    args: ['--no-sandbox','--use-gl=angle','--use-angle=metal','--window-size=1400,900'],
    protocolTimeout: 1800000, userDataDir: '/tmp/fc-treekeys' });
  const p = (await b.pages())[0];
  const errs = []; p.on('pageerror', (e) => errs.push(String(e).slice(0,120)));
  await p.goto(URL, { waitUntil: 'domcontentloaded', timeout: 300000 });
  const t0 = Date.now();
  while (Date.now() - t0 < 300000) { if (await p.evaluate(() => !!(window.fcInstance && window.fcInstance._malloc))) break; await sl(1000); }
  for (let i=0;i<40;i++){ await sl(3000); await run(p,'import sys,FreeCAD\nsys.__stderr__.write("RDY %d\\n"%len(FreeCAD.__unit_test__))\nsys.__stderr__.flush()\n'); await sl(1200);
    const m=[...(await readLog(p)).matchAll(/RDY (\d+)/g)].pop(); if(m&&+m[1]>0) break; }

  await run(p, [
    'import sys',
    'import FreeCAD as App, FreeCADGui as Gui',
    'from PySide6 import QtWidgets, QtCore',
    'd = App.newDocument("Keys")',
    'for n, L in (("Alpha", 10), ("Beta", 20)):',
    '    b = d.addObject("Part::Box", n); b.Length = L; b.Width = L; b.Height = L',
    'd.recompute()',
    'mw = Gui.getMainWindow()',
    'trees = [t for t in mw.findChildren(QtWidgets.QTreeWidget) + mw.findChildren(QtWidgets.QTreeView) if t.isVisible()]',
    'tree = trees[0] if trees else None',
    'if tree is not None:',
    '    tree.setFocus(QtCore.Qt.MouseFocusReason)',
    'Gui.Selection.clearSelection()',
    'Gui.Selection.addSelection(d.Name, "Beta")',
    'fw = QtWidgets.QApplication.focusWidget()',
    'sys.__stderr__.write("STATE objs=%s sel=%s focus=%s tree=%s\\n" % (',
    '    [o.Name for o in d.Objects], [o.Name for o in Gui.Selection.getSelection()],',
    '    fw.__class__.__name__ if fw else None, tree.__class__.__name__ if tree else None))',
    'sys.__stderr__.flush()'
  ].join('\n'));
  await sl(4000);
  console.log(await grab(p, 'STATE'));

  await p.keyboard.press('Delete');
  await sl(3500);
  await run(p, [
    'import sys, FreeCAD as App',
    'd = App.getDocument("Keys")',
    'sys.__stderr__.write("AFTERDEL objs=%s\\n" % [o.Name for o in d.Objects]); sys.__stderr__.flush()'
  ].join('\n'));
  await sl(2500);
  console.log(await grab(p, 'AFTERDEL'));

  // and the standard menu route, for comparison: Std_Delete via the command system
  await run(p, [
    'import sys',
    'import FreeCAD as App, FreeCADGui as Gui',
    'd = App.getDocument("Keys")',
    'Gui.Selection.clearSelection(); Gui.Selection.addSelection(d.Name, "Beta")',
    'try:',
    '    Gui.runCommand("Std_Delete", 0)',
    '    sys.__stderr__.write("CMDDEL ran\\n")',
    'except Exception as e:',
    '    sys.__stderr__.write("CMDDEL EXC %s\\n" % str(e)[:80])',
    'sys.__stderr__.flush()'
  ].join('\n'));
  await sl(3500);
  await run(p, [
    'import sys, FreeCAD as App',
    'd = App.getDocument("Keys")',
    'sys.__stderr__.write("AFTERCMD objs=%s\\n" % [o.Name for o in d.Objects]); sys.__stderr__.flush()'
  ].join('\n'));
  await sl(2500);
  console.log(await grab(p, 'CMDDEL') + ' -> ' + await grab(p, 'AFTERCMD'));
  console.log('page errors: ' + (errs.length ? errs.slice(0,3).join(' | ') : 'none'));
  await b.close().catch(()=>{}); process.exit(0);
})().catch((e)=>{console.log('DRIVER '+String(e).slice(0,200));process.exit(0);});
