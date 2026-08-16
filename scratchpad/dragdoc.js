// Last two never-driven interactions:
//   1. drag an object onto a Group in the tree (reparenting by drag-and-drop)
//   2. switch between two open documents via the Windows menu, and confirm the
//      3D view and the tree both follow
const puppeteer = require('puppeteer-core');
const CHROME = process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';  // set CHROME_PATH to run off macOS
const sl = (ms) => new Promise((r) => setTimeout(r, ms));
const run = (p, c) => p.evaluate((code) => {
  const m = window.fcInstance;
  const n = new TextEncoder().encode(code).length + 1; const q = m._malloc(n); m.stringToUTF8(code, q, n);
  (window.fcRunPy || ((mm, pp) => { mm._fcweb_run_python(pp); mm._free(pp); }))(m, q);
}, c);
const readLog = (p) => p.evaluate(() => document.getElementById('log').textContent);
const grab = async (p, k) => { const m = (await readLog(p)).match(new RegExp(k + ' [^\\n]*', 'g')) || []; return m.length ? m[m.length-1] : '(none)'; };
const PY = (l) => l.join('\n');
const locate = async (p, label) => {
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
    'sys.__stderr__.write("LOC_' + label + ' %s\\n" % out); sys.__stderr__.flush()'
  ]));
  await sl(2200);
  return /LOC_\w+ (\d+) (\d+)/.exec(await grab(p, 'LOC_' + label));
};
(async () => {
  const b = await puppeteer.launch({ executablePath: CHROME, headless: false, defaultViewport: null,
    args: ['--no-sandbox','--use-gl=angle','--use-angle=metal','--window-size=1400,900'],
    protocolTimeout: 1800000, userDataDir: '/tmp/fc-dragdoc' });
  const p = (await b.pages())[0];
  const errs = []; p.on('pageerror', (e) => errs.push(String(e).slice(0,120)));
  await p.goto(process.argv[2] || 'http://localhost:8792/index.html', { waitUntil: 'domcontentloaded', timeout: 300000 });
  const t0 = Date.now();
  while (Date.now() - t0 < 300000) { if (await p.evaluate(() => !!(window.fcInstance && window.fcInstance._malloc))) break; await sl(1000); }
  for (let i=0;i<40;i++){ await sl(3000); await run(p,'import sys,FreeCAD\nsys.__stderr__.write("RDY %d\\n"%len(FreeCAD.__unit_test__))\nsys.__stderr__.flush()\n'); await sl(1200);
    const m=[...(await readLog(p)).matchAll(/RDY (\d+)/g)].pop(); if(m&&+m[1]>0) break; }

  await run(p, PY([
    'import FreeCAD as App, FreeCADGui as Gui',
    'from PySide6 import QtWidgets',
    'd = App.newDocument("DD")',
    'g = d.addObject("App::DocumentObjectGroup","Bucket")',
    'o = d.addObject("Part::Box","Loose"); o.Length=o.Width=o.Height=10',
    'd.recompute()',
    'Gui.activateWorkbench("PartWorkbench"); Gui.SendMsgToActiveView("ViewFit")',
    'mw = Gui.getMainWindow()',
    'for dw in mw.findChildren(QtWidgets.QDockWidget):',
    '    if "model" in dw.windowTitle().strip().lower(): dw.show(); dw.raise_()'
  ]));
  await sl(6000);

  const src = await locate(p, 'Loose');
  const dst = await locate(p, 'Bucket');
  if (src && dst) {
    await p.mouse.move(+src[1], +src[2]); await sl(400);
    await p.mouse.down(); await sl(400);
    // move in steps so Qt starts a drag rather than reading it as a click
    for (let i = 1; i <= 10; i++) {
      await p.mouse.move(+src[1] + (+dst[1] - +src[1]) * i / 10, +src[2] + (+dst[2] - +src[2]) * i / 10);
      await sl(150);
    }
    await sl(600); await p.mouse.up(); await sl(3000);
    await run(p, PY([
      'import sys, FreeCAD as App',
      'g = App.getDocument("DD").getObject("Bucket")',
      'sys.__stderr__.write("GROUP %s\\n" % [o.Name for o in g.Group]); sys.__stderr__.flush()'
    ]));
    await sl(1800);
    const gr = await grab(p, 'GROUP');
    console.log(`tree drag-and-drop: ${gr}  ${gr.includes('Loose') ? '*** the drop reparented it ***' : '(object did not move into the group)'}`);
  } else console.log(`tree drag-and-drop: could not locate items (src=${!!src} dst=${!!dst})`);

  // ---- 2. multi-document switching via the Windows menu
  await run(p, PY([
    'import FreeCAD as App, FreeCADGui as Gui',
    'd2 = App.newDocument("SECOND")',
    'o = d2.addObject("Part::Sphere","Ball"); o.Radius = 7; d2.recompute()',
    'Gui.SendMsgToActiveView("ViewFit")'
  ]));
  await sl(5000);
  await run(p, PY([
    'import sys',
    'from PySide6 import QtWidgets',
    'import FreeCADGui as Gui',
    'mw = Gui.getMainWindow(); out="none"',
    'for a in mw.menuBar().actions():',
    '    if a.text().replace("&","").strip().lower().startswith("window"):',
    '        r = mw.menuBar().actionGeometry(a); g = mw.menuBar().mapToGlobal(r.center())',
    '        out = "%d %d" % (g.x(), g.y())',
    'sys.__stderr__.write("WINMENU %s\\n" % out); sys.__stderr__.flush()'
  ]));
  await sl(2200);
  const wm = /WINMENU (\d+) (\d+)/.exec(await grab(p, 'WINMENU'));
  if (!wm) console.log('multi-document: no Windows menu found -- ' + await grab(p, 'WINMENU'));
  else {
    await p.mouse.click(+wm[1], +wm[2]); await sl(2500);
    await run(p, PY([
      'import sys',
      'from PySide6 import QtWidgets',
      'import FreeCADGui as Gui',
      'out="none"',
      'for m in QtWidgets.QApplication.topLevelWidgets():',
      '    if isinstance(m, QtWidgets.QMenu) and m.isVisible():',
      '        for a in m.actions():',
      '            if "DD" in a.text():',
      '                g = m.mapToGlobal(m.actionGeometry(a).center()); out = "%d %d" % (g.x(), g.y())',
      'sys.__stderr__.write("DDENTRY %s\\n" % out); sys.__stderr__.flush()'
    ]));
    await sl(2200);
    const de = /DDENTRY (\d+) (\d+)/.exec(await grab(p, 'DDENTRY'));
    if (!de) console.log('multi-document: the Windows menu had no entry for the first document -- ' + await grab(p, 'DDENTRY'));
    else {
      await p.mouse.click(+de[1], +de[2]); await sl(3000);
      await run(p, PY([
        'import sys',
        'import FreeCAD as App, FreeCADGui as Gui',
        'ad = App.ActiveDocument.Name if App.ActiveDocument else None',
        'gd = Gui.ActiveDocument.Document.Name if Gui.ActiveDocument else None',
        'sys.__stderr__.write("ACTIVE %s %s\\n" % (ad, gd)); sys.__stderr__.flush()'
      ]));
      await sl(1800);
      const ac = await grab(p, 'ACTIVE');
      console.log(`multi-document switch: ${ac}  ${ac.includes('DD DD') ? '*** the menu switched documents ***' : '(did not switch)'}`);
    }
  }
  console.log('page errors: ' + (errs.length ? errs.slice(0,3).join(' | ') : 'none'));
  await b.close().catch(()=>{}); process.exit(0);
})().catch((e)=>{console.log('DRIVER '+String(e).slice(0,200));process.exit(0);});
