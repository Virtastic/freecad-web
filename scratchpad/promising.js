// Verify the promising event dispatcher: the two interactions that silently did nothing
// must now work from REAL input, and routing every Qt event through JSPI must not cost
// interaction frame rate.
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
const PY = (l) => l.join('\n');
(async () => {
  const b = await puppeteer.launch({ executablePath: CHROME, headless: false, defaultViewport: null,
    args: ['--no-sandbox','--use-gl=angle','--use-angle=metal','--window-size=1400,900'],
    protocolTimeout: 1800000, userDataDir: '/tmp/fc-promising' });
  const p = (await b.pages())[0];
  const errs = []; p.on('pageerror', (e) => errs.push(String(e).split('\n')[0].slice(0,140)));
  await p.goto(process.argv[2] || 'http://localhost:8792/index.html', { waitUntil: 'domcontentloaded', timeout: 300000 });
  const t0 = Date.now();
  while (Date.now() - t0 < 300000) { if (await p.evaluate(() => !!(window.fcInstance && window.fcInstance._malloc))) break; await sl(1000); }
  for (let i=0;i<40;i++){ await sl(3000); await run(p,'import sys,FreeCAD\nsys.__stderr__.write("RDY %d\\n"%len(FreeCAD.__unit_test__))\nsys.__stderr__.flush()\n'); await sl(1200);
    const m=[...(await readLog(p)).matchAll(/RDY (\d+)/g)].pop(); if(m&&+m[1]>0) break; }
  console.log('dispatcher installed: ' + await p.evaluate(() => !!(window.fcInstance && window.fcInstance.__fcwebEventDispatchInstalled)));

  await run(p, PY([
    'import FreeCAD as App, FreeCADGui as Gui',
    'from PySide6 import QtWidgets',
    'd = App.newDocument("PR")',
    'g = d.addObject("App::DocumentObjectGroup","Bucket")',
    'o = d.addObject("Part::Box","Loose"); o.Length=o.Width=o.Height=10; d.recompute()',
    'Gui.activateWorkbench("PartWorkbench")',
    'Gui.SendMsgToActiveView("ViewAxonometric"); Gui.SendMsgToActiveView("ViewFit")',
    'mw = Gui.getMainWindow()',
    'for dw in mw.findChildren(QtWidgets.QDockWidget):',
    '    if "model" in dw.windowTitle().strip().lower(): dw.show(); dw.raise_()'
  ]));
  await sl(6000);

  // --- 1. modal dialog from a real click
  await run(p, PY([
    'import sys',
    'import FreeCADGui as Gui',
    'mw = Gui.getMainWindow(); out="none"',
    'for a in mw.menuBar().actions():',
    '    if a.text().replace("&","").strip().lower().startswith("help"):',
    '        g = mw.menuBar().mapToGlobal(mw.menuBar().actionGeometry(a).center()); out="%d %d"%(g.x(),g.y())',
    'sys.__stderr__.write("HELP %s\\n" % out); sys.__stderr__.flush()'
  ]));
  await sl(2200);
  const hm = /HELP (\d+) (\d+)/.exec(await grab(p, 'HELP'));
  if (hm) {
    await p.mouse.click(+hm[1], +hm[2]); await sl(2500);
    await run(p, PY([
      'import sys',
      'from PySide6 import QtWidgets',
      'out="none"',
      'for m in QtWidgets.QApplication.topLevelWidgets():',
      '    if isinstance(m, QtWidgets.QMenu) and m.isVisible():',
      '        for a in m.actions():',
      '            if "about" in a.text().replace("&","").strip().lower() and "qt" not in a.text().lower():',
      '                g = m.mapToGlobal(m.actionGeometry(a).center()); out="%d %d"%(g.x(),g.y())',
      'sys.__stderr__.write("ABOUT %s\\n" % out); sys.__stderr__.flush()'
    ]));
    await sl(2200);
    const ab = /ABOUT (\d+) (\d+)/.exec(await grab(p, 'ABOUT'));
    if (ab) {
      const before = errs.length;
      await p.mouse.click(+ab[1], +ab[2]); await sl(6000);
      await run(p, PY([
        'import sys',
        'from PySide6 import QtWidgets',
        'ds = [type(w).__name__ for w in QtWidgets.QApplication.topLevelWidgets() if isinstance(w, QtWidgets.QDialog) and w.isVisible()]',
        'sys.__stderr__.write("DLG %s\\n" % ds); sys.__stderr__.flush()'
      ]));
      await sl(2500);
      const dlg = await grab(p, 'DLG');
      const ne = errs.slice(before);
      console.log(`click Help > About: ${dlg}  errors=${ne.length ? ne.join(' | ') : 'none'}  ${dlg.includes('Dialog') && !ne.length ? '*** a real click opens a modal dialog ***' : '!!! still broken !!!'}`);
      // close it with a real Escape, which also re-checks the popup path
      await p.keyboard.press('Escape'); await sl(2000);
      await run(p, PY([
        'import sys',
        'from PySide6 import QtWidgets',
        'for w in QtWidgets.QApplication.topLevelWidgets():',
        '    if isinstance(w, QtWidgets.QDialog) and w.isVisible(): w.close()',
        'sys.__stderr__.write("CLOSED ok\\n"); sys.__stderr__.flush()'
      ]));
      await sl(2500);
    } else console.log('no About entry: ' + await grab(p, 'ABOUT'));
  }

  // --- 2. tree drag-and-drop
  const loc = async (label) => {
    await run(p, PY([
      'import sys',
      'from PySide6 import QtWidgets, QtCore',
      'import FreeCADGui as Gui',
      'mw = Gui.getMainWindow(); out="none"',
      'for t in mw.findChildren(QtWidgets.QTreeWidget):',
      '    if not t.isVisible(): continue',
      '    m = t.model()',
      '    r = m.match(m.index(0,0), QtCore.Qt.DisplayRole, "' + label + '", 1, QtCore.Qt.MatchRecursive|QtCore.Qt.MatchExactly)',
      '    if r:',
      '        t.expandAll(); t.scrollTo(r[0]); g = t.viewport().mapToGlobal(t.visualRect(r[0]).center())',
      '        if g.x()>0 and g.y()>0: out = "%d %d" % (g.x(), g.y()); break',
      'sys.__stderr__.write("L' + label + ' %s\\n" % out); sys.__stderr__.flush()'
    ]));
    await sl(2200);
    return /L\w+ (\d+) (\d+)/.exec(await grab(p, 'L' + label));
  };
  const s = await loc('Loose'), t = await loc('Bucket');
  if (s && t) {
    const before = errs.length;
    await p.mouse.move(+s[1], +s[2]); await sl(400); await p.mouse.down(); await sl(400);
    for (let i = 1; i <= 10; i++) { await p.mouse.move(+s[1] + (+t[1]-+s[1])*i/10, +s[2] + (+t[2]-+s[2])*i/10); await sl(160); }
    await sl(600); await p.mouse.up(); await sl(4000);
    await run(p, PY([
      'import sys, FreeCAD as App',
      'sys.__stderr__.write("GROUP %s\\n" % [o.Name for o in App.getDocument("PR").getObject("Bucket").Group]); sys.__stderr__.flush()'
    ]));
    await sl(2000);
    const gr = await grab(p, 'GROUP');
    const ne = errs.slice(before);
    console.log(`tree drag-and-drop: ${gr}  errors=${ne.length ? ne.join(' | ') : 'none'}  ${gr.includes('Loose') ? '*** the drop reparented it ***' : '(still not reparented)'}`);
  } else console.log('drag: items not locatable');

  // --- 3. interaction frame rate: every Qt event now crosses a JSPI boundary
  await run(p, PY([
    'import sys',
    'from PySide6 import QtWidgets, QtCore',
    'import FreeCADGui as Gui',
    'mdi = Gui.getMainWindow().findChild(QtWidgets.QMdiArea); sub = mdi.currentSubWindow()',
    'c = sub.mapToGlobal(QtCore.QPoint(sub.width()//2, sub.height()//2))',
    'sys.__stderr__.write("CTR %d %d\\n" % (c.x(), c.y())); sys.__stderr__.flush()'
  ]));
  await sl(2200);
  const ctr = /CTR (\d+) (\d+)/.exec(await grab(p, 'CTR'));
  if (ctr) {
    await p.evaluate(() => { window.__f = 0; const t = () => { window.__f++; requestAnimationFrame(t); }; requestAnimationFrame(t); });
    const t1 = Date.now();
    await p.mouse.move(+ctr[1], +ctr[2]); await p.mouse.down({ button: 'middle' });
    for (let i = 0; i < 40; i++) { await p.mouse.move(+ctr[1] + 90*Math.cos(i/5), +ctr[2] + 90*Math.sin(i/5)); await sl(45); }
    await p.mouse.up({ button: 'middle' });
    const frames = await p.evaluate(() => window.__f);
    console.log(`orbit fps during 40 real drags: ${(frames / ((Date.now()-t1)/1000)).toFixed(1)}`);
  }
  console.log('all page errors: ' + (errs.length ? errs.slice(0,4).join(' | ') : 'none'));
  await b.close().catch(()=>{}); process.exit(0);
})().catch((e)=>{console.log('DRIVER '+String(e).slice(0,200));process.exit(0);});
