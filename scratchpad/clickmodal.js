// Does a modal dialog opened by a REAL MOUSE CLICK work? Every dialog verified so far was
// triggered through the Python bridge, which is a promising (JSPI-capable) stack.
// A menu click is a plain DOM callback -- if a nested loop cannot suspend there, then the
// drag failure is one instance of a much larger class.
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
    protocolTimeout: 1800000, userDataDir: '/tmp/fc-clickmodal' });
  const p = (await b.pages())[0];
  const errs = []; p.on('pageerror', (e) => errs.push(String(e).split('\n')[0].slice(0,140)));
  await p.goto(process.argv[2] || 'http://localhost:8792/index.html', { waitUntil: 'domcontentloaded', timeout: 300000 });
  const t0 = Date.now();
  while (Date.now() - t0 < 300000) { if (await p.evaluate(() => !!(window.fcInstance && window.fcInstance._malloc))) break; await sl(1000); }
  for (let i=0;i<40;i++){ await sl(3000); await run(p,'import sys,FreeCAD\nsys.__stderr__.write("RDY %d\\n"%len(FreeCAD.__unit_test__))\nsys.__stderr__.flush()\n'); await sl(1200);
    const m=[...(await readLog(p)).matchAll(/RDY (\d+)/g)].pop(); if(m&&+m[1]>0) break; }
  await run(p, 'import FreeCAD as App, FreeCADGui as Gui\nApp.newDocument("CM")\nGui.activateWorkbench("PartWorkbench")\n');
  await sl(4000);

  // locate the Help menu and its About entry, then click them for real
  await run(p, PY([
    'import sys',
    'from PySide6 import QtWidgets',
    'import FreeCADGui as Gui',
    'mw = Gui.getMainWindow(); out="none"',
    'for a in mw.menuBar().actions():',
    '    if a.text().replace("&","").strip().lower().startswith("help"):',
    '        g = mw.menuBar().mapToGlobal(mw.menuBar().actionGeometry(a).center()); out="%d %d"%(g.x(),g.y())',
    'sys.__stderr__.write("HELP %s\\n" % out); sys.__stderr__.flush()'
  ]));
  await sl(2200);
  const hm = /HELP (\d+) (\d+)/.exec(await grab(p, 'HELP'));
  if (!hm) { console.log('no Help menu: ' + await grab(p, 'HELP')); await b.close(); process.exit(0); }
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
  if (!ab) { console.log('no About entry: ' + await grab(p, 'ABOUT')); await b.close(); process.exit(0); }
  const before = errs.length;
  await p.mouse.click(+ab[1], +ab[2]); await sl(6000);
  // is a modal dialog actually up? ask through the bridge (it runs on its own stack)
  await run(p, PY([
    'import sys',
    'from PySide6 import QtWidgets',
    'ds = [type(w).__name__ for w in QtWidgets.QApplication.topLevelWidgets() if isinstance(w, QtWidgets.QDialog) and w.isVisible()]',
    'sys.__stderr__.write("DLG %s\\n" % ds); sys.__stderr__.flush()'
  ]));
  await sl(2500);
  const dlg = await grab(p, 'DLG');
  const newErrs = errs.slice(before);
  console.log(`click Help > About: ${dlg}`);
  console.log(`  errors raised by the click: ${newErrs.length ? newErrs.join(' | ') : 'none'}`);
  console.log(`  ${dlg.includes('Dialog') && !newErrs.length ? '*** a real click CAN open a modal dialog ***' : '!!! the click path cannot run a modal dialog !!!'}`);
  // close it and confirm the app is still alive
  await run(p, PY([
    'import sys',
    'from PySide6 import QtWidgets',
    'for w in QtWidgets.QApplication.topLevelWidgets():',
    '    if isinstance(w, QtWidgets.QDialog) and w.isVisible(): w.close()',
    'import FreeCAD as App',
    'd = App.getDocument("CM"); d.addObject("Part::Box","Alive"); d.recompute()',
    'sys.__stderr__.write("ALIVE %s\\n" % [o.Name for o in d.Objects]); sys.__stderr__.flush()'
  ]));
  await sl(3000);
  console.log('after: ' + await grab(p, 'ALIVE'));
  console.log('all page errors: ' + (errs.length ? errs.slice(0,3).join(' | ') : 'none'));
  await b.close().catch(()=>{}); process.exit(0);
})().catch((e)=>{console.log('DRIVER '+String(e).slice(0,200));process.exit(0);});
