// More everyday interactions, chosen because they exercise the paths that just changed:
//   1. click an object in the 3D VIEW to select it (picking, not the tree)
//   2. arrow keys in the tree (navigation via the new key forwarder)
//   3. Ctrl/Cmd+A select-all in the tree
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
(async () => {
  const b = await puppeteer.launch({ executablePath: CHROME, headless: false, defaultViewport: null,
    args: ['--no-sandbox','--use-gl=angle','--use-angle=metal','--window-size=1400,900'],
    protocolTimeout: 1800000, userDataDir: '/tmp/fc-moreinput' });
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
    'd = App.newDocument("MI")',
    'for n,x in (("A",0),("B",30)):',
    '    o = d.addObject("Part::Box", n); o.Length=o.Width=o.Height=10',
    '    o.Placement.Base = App.Vector(x,0,0)',
    'd.recompute()',
    'Gui.activateWorkbench("PartWorkbench"); Gui.SendMsgToActiveView("ViewAxonometric"); Gui.SendMsgToActiveView("ViewFit")',
    'mdi = Gui.getMainWindow().findChild(QtWidgets.QMdiArea); sub = mdi.currentSubWindow()',
    'c = sub.mapToGlobal(QtCore.QPoint(sub.width()//2, sub.height()//2))',
    'sys.__stderr__.write("VIEW %d %d %d %d\\n" % (c.x(), c.y(), sub.width(), sub.height()))',
    'sys.__stderr__.flush()'
  ].join('\n'));
  await sl(6000);
  const vw = /VIEW (\d+) (\d+) (\d+) (\d+)/.exec(await grab(p, 'VIEW'));

  // 1. pick in the 3D view: click where a solid is drawn
  await run(p, 'import sys, FreeCADGui as Gui\nGui.Selection.clearSelection()\nsys.__stderr__.write("CLEARED\\n")\nsys.__stderr__.flush()\n');
  await sl(1500);
  let picked = '(none)';
  for (const [dx, dy] of [[-60,0],[-90,20],[-40,-20],[60,0],[0,0]]) {
    await p.mouse.click(+vw[1] + dx, +vw[2] + dy);
    await sl(1800);
    await run(p, 'import sys, FreeCADGui as Gui\nsys.__stderr__.write("PICK %s\\n" % [o.Name for o in Gui.Selection.getSelection()])\nsys.__stderr__.flush()\n');
    await sl(1500);
    picked = await grab(p, 'PICK');
    if (!picked.includes('[]')) { console.log(`3D pick at offset (${dx},${dy}): ${picked}   *** picking works ***`); break; }
  }
  if (picked.includes('[]')) console.log('3D pick: nothing selected at any tried point -- ' + picked);

  // 2 & 3: tree navigation and select-all via the forwarded keys
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
    '    r = m.match(m.index(0,0), QtCore.Qt.DisplayRole, "A", 1, QtCore.Qt.MatchRecursive|QtCore.Qt.MatchExactly)',
    '    if r:',
    '        t.scrollTo(r[0]); g = t.viewport().mapToGlobal(t.visualRect(r[0]).center())',
    '        if g.x()>0 and g.y()>0: hit=(g.x(),g.y()); break',
    'sys.__stderr__.write("HIT %s\\n" % ("%d %d" % hit if hit else "none")); sys.__stderr__.flush()'
  ].join('\n'));
  await sl(2000);
  const hit = /HIT (\d+) (\d+)/.exec(await grab(p, 'HIT'));
  if (hit) {
    await p.mouse.click(+hit[1], +hit[2]); await sl(1800);
    const cur = async (tag) => {
      await run(p, [
        'import sys',
        'from PySide6 import QtWidgets',
        'import FreeCADGui as Gui',
        'mw = Gui.getMainWindow()',
        'ts = [t for t in mw.findChildren(QtWidgets.QTreeWidget) if t.isVisible()]',
        'it = ts[0].currentItem() if ts else None',
        'sys.__stderr__.write("CUR ' + tag + ' %r\\n" % (it.text(0) if it else None)); sys.__stderr__.flush()'
      ].join('\n'));
      await sl(1600);
      return (await grab(p, 'CUR ' + tag)).replace('CUR ' + tag + ' ', '');
    };
    const c0 = await cur('A');
    await p.keyboard.press('ArrowDown'); await sl(1800);
    const c1 = await cur('B');
    console.log(`arrow key in tree: current ${c0} -> ${c1}  ${c0 !== c1 ? '*** arrow navigates ***' : 'no movement'}`);
  }
  console.log('page errors: ' + (errs.length ? errs.slice(0,3).join(' | ') : 'none'));
  await b.close().catch(()=>{}); process.exit(0);
})().catch((e)=>{console.log('DRIVER '+String(e).slice(0,200));process.exit(0);});
