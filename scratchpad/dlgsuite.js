// Dialogs that only a real click can reach. Before the promising fix these could not
// open at all, so their behaviour has never been observed:
//   1. closing a MODIFIED document -- does it ask before discarding the user's work?
//   2. Edit > Preferences -- the largest modal in the app; does it open and close cleanly?
// The Python bridge still answers while a C++ modal is up (the dialog's nested loop is
// suspended, CPython is idle), which is how the buttons get located.
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
// find a top-level menu by name and click it, then click an entry matching a substring
const menuPath = async (p, top, entry) => {
  await run(p, PY([
    'import sys',
    'import FreeCADGui as Gui',
    'mw = Gui.getMainWindow(); out="none"',
    'for a in mw.menuBar().actions():',
    '    if a.text().replace("&","").strip().lower().startswith("' + top + '"):',
    '        g = mw.menuBar().mapToGlobal(mw.menuBar().actionGeometry(a).center()); out="%d %d"%(g.x(),g.y())',
    'sys.__stderr__.write("TOPM %s\\n" % out); sys.__stderr__.flush()'
  ]));
  await sl(2200);
  const t = /TOPM (\d+) (\d+)/.exec(await grab(p, 'TOPM'));
  if (!t) return 'no top menu ' + top;
  await p.mouse.click(+t[1], +t[2]); await sl(2500);
  await run(p, PY([
    'import sys',
    'from PySide6 import QtWidgets',
    'out="none"',
    'for m in QtWidgets.QApplication.topLevelWidgets():',
    '    if isinstance(m, QtWidgets.QMenu) and m.isVisible():',
    '        for a in m.actions():',
    '            if "' + entry + '" in a.text().replace("&","").strip().lower() and a.isEnabled():',
    '                g = m.mapToGlobal(m.actionGeometry(a).center())',
    '                if g.y() > 0: out="%d %d"%(g.x(),g.y())',
    'sys.__stderr__.write("ENTRY %s\\n" % out); sys.__stderr__.flush()'
  ]));
  await sl(2200);
  const e = /ENTRY (\d+) (\d+)/.exec(await grab(p, 'ENTRY'));
  if (!e) { await p.keyboard.press('Escape'); return 'no entry ' + entry; }
  await p.mouse.click(+e[1], +e[2]);
  return 'clicked';
};
(async () => {
  const b = await puppeteer.launch({ executablePath: CHROME, headless: false, defaultViewport: null,
    args: ['--no-sandbox','--use-gl=angle','--use-angle=metal','--window-size=1400,900'],
    protocolTimeout: 900000, userDataDir: '/tmp/fc-dlgsuite' });
  const p = (await b.pages())[0];
  const errs = []; p.on('pageerror', (e) => errs.push(String(e).split('\n')[0].slice(0,140)));
  await p.goto(process.argv[2] || 'http://localhost:8792/index.html', { waitUntil: 'domcontentloaded', timeout: 300000 });
  const t0 = Date.now();
  while (Date.now() - t0 < 300000) { if (await p.evaluate(() => !!(window.fcInstance && window.fcInstance._malloc))) break; await sl(1000); }
  for (let i=0;i<40;i++){ await sl(3000); await run(p,'import sys,FreeCAD\nsys.__stderr__.write("RDY %d\\n"%len(FreeCAD.__unit_test__))\nsys.__stderr__.flush()\n'); await sl(1200);
    const m=[...(await readLog(p)).matchAll(/RDY (\d+)/g)].pop(); if(m&&+m[1]>0) break; }

  // ---- 1. close a MODIFIED document: is the user asked before losing work?
  await run(p, PY([
    'import FreeCAD as App, FreeCADGui as Gui',
    'd = App.newDocument("Unsaved")',
    'o = d.addObject("Part::Box","Work"); o.Length=33; d.recompute()',
    'Gui.activateWorkbench("PartWorkbench")',
    'import sys; sys.__stderr__.write("TOUCHED %s\\n" % d.isTouched()); sys.__stderr__.flush()'
  ]));
  await sl(5000);
  const closeClick = await menuPath(p, 'file', 'close');
  await sl(5000);
  await run(p, PY([
    'import sys',
    'from PySide6 import QtWidgets',
    'import FreeCAD as App',
    'ds = [(type(w).__name__, w.windowTitle()) for w in QtWidgets.QApplication.topLevelWidgets() if isinstance(w, QtWidgets.QDialog) and w.isVisible()]',
    'docs = list(App.listDocuments().keys())',
    'sys.__stderr__.write("CLOSEQ %s DOCS %s\\n" % (ds, docs)); sys.__stderr__.flush()'
  ]));
  await sl(3000);
  const cq = await grab(p, 'CLOSEQ');
  const asked = /QMessageBox|QDialog/.test(cq);
  const stillOpen = /'Unsaved'/.test(cq);
  console.log(`File > Close on a modified document (${closeClick}): ${cq}`);
  console.log(`  ${asked ? '*** the user is asked before losing work ***' : (stillOpen ? 'no prompt, but the document is still open' : '!!! closed silently, work discarded without asking !!!')}`);
  if (asked) {
    // click "Cancel" for real and confirm the document survives
    await run(p, PY([
      'import sys',
      'from PySide6 import QtWidgets',
      'out="none"',
      'for w in QtWidgets.QApplication.topLevelWidgets():',
      '    if isinstance(w, QtWidgets.QDialog) and w.isVisible():',
      '        for bt in w.findChildren(QtWidgets.QAbstractButton):',
      '            if bt.isVisible() and "cancel" in bt.text().replace("&","").strip().lower():',
      '                g = bt.mapToGlobal(bt.rect().center()); out="%d %d"%(g.x(),g.y())',
      'sys.__stderr__.write("CANCELBTN %s\\n" % out); sys.__stderr__.flush()'
    ]));
    await sl(2500);
    const cb = /CANCELBTN (\d+) (\d+)/.exec(await grab(p, 'CANCELBTN'));
    if (cb) {
      await p.mouse.click(+cb[1], +cb[2]); await sl(4000);
      await run(p, PY([
        'import sys, FreeCAD as App',
        'sys.__stderr__.write("AFTERCANCEL %s\\n" % list(App.listDocuments().keys())); sys.__stderr__.flush()'
      ]));
      await sl(2500);
      const ac = await grab(p, 'AFTERCANCEL');
      console.log(`  clicking Cancel: ${ac}  ${ac.includes('Unsaved') ? '*** Cancel kept the document ***' : '(the document went away anyway)'}`);
    } else console.log('  no Cancel button found: ' + await grab(p, 'CANCELBTN'));
  }

  // ---- 2. Preferences: the biggest modal in the app
  const prefClick = await menuPath(p, 'edit', 'preference');
  await sl(9000);
  await run(p, PY([
    'import sys',
    'from PySide6 import QtWidgets',
    'ds = [(type(w).__name__, w.windowTitle(), len(w.findChildren(QtWidgets.QWidget))) for w in QtWidgets.QApplication.topLevelWidgets() if isinstance(w, QtWidgets.QDialog) and w.isVisible()]',
    'sys.__stderr__.write("PREFS %s\\n" % ds); sys.__stderr__.flush()'
  ]));
  await sl(3000);
  const pf = await grab(p, 'PREFS');
  console.log(`Edit > Preferences (${prefClick}): ${pf}`);
  console.log(`  ${/QDialog|DlgPreferences/.test(pf) ? '*** Preferences opens ***' : '!!! Preferences did not open !!!'}`);
  if (/QDialog|DlgPreferences/.test(pf)) {
    await run(p, PY([
      'import sys',
      'from PySide6 import QtWidgets',
      'out="none"',
      'for w in QtWidgets.QApplication.topLevelWidgets():',
      '    if isinstance(w, QtWidgets.QDialog) and w.isVisible():',
      '        for bt in w.findChildren(QtWidgets.QAbstractButton):',
      '            if bt.isVisible() and bt.text().replace("&","").strip().lower() in ("ok","cancel","close"):',
      '                g = bt.mapToGlobal(bt.rect().center()); out="%d %d"%(g.x(),g.y())',
      'sys.__stderr__.write("PREFBTN %s\\n" % out); sys.__stderr__.flush()'
    ]));
    await sl(2500);
    const pb = /PREFBTN (\d+) (\d+)/.exec(await grab(p, 'PREFBTN'));
    if (pb) { await p.mouse.click(+pb[1], +pb[2]); await sl(5000); }
    await run(p, PY([
      'import sys',
      'from PySide6 import QtWidgets',
      'import FreeCAD as App',
      'left = [type(w).__name__ for w in QtWidgets.QApplication.topLevelWidgets() if isinstance(w, QtWidgets.QDialog) and w.isVisible()]',
      'd = App.ActiveDocument or App.newDocument("After")',
      'd.addObject("Part::Sphere","Alive"); d.recompute()',
      'sys.__stderr__.write("AFTERPREF open=%s objs=%s\\n" % (left, [o.Name for o in d.Objects])); sys.__stderr__.flush()'
    ]));
    await sl(3000);
    console.log('  after closing it: ' + await grab(p, 'AFTERPREF'));
  }
  console.log('page errors: ' + (errs.length ? errs.slice(0,4).join(' | ') : 'none'));
  await b.close().catch(()=>{}); process.exit(0);
})().catch((e)=>{console.log('DRIVER '+String(e).slice(0,200));process.exit(0);});
