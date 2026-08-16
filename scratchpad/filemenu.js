// How a user gets work OUT: File > Save and File > Export, clicked for real. These go
// through the main-thread file bridge and end in a browser download, so the check is
// whether a file actually lands on disk -- not whether a handler was called.
const puppeteer = require('puppeteer-core');
const fs = require('fs');
const CHROME = process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';  // set CHROME_PATH to run off macOS
const DL = '/tmp/fc-downloads';
const sl = (ms) => new Promise((r) => setTimeout(r, ms));
const run = (p, c) => p.evaluate((code) => {
  const m = window.fcInstance;
  const n = new TextEncoder().encode(code).length + 1; const q = m._malloc(n); m.stringToUTF8(code, q, n);
  (window.fcRunPy || ((mm, pp) => { mm._fcweb_run_python(pp); mm._free(pp); }))(m, q);
}, c);
const readLog = (p) => p.evaluate(() => document.getElementById('log').textContent);
const grab = async (p, k) => { const m = (await readLog(p)).match(new RegExp(k + ' [^\\n]*', 'g')) || []; return m.length ? m[m.length-1] : '(none)'; };
const PY = (l) => l.join('\n');
const menuClick = async (p, top, entry) => {
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
  if (!t) return 'no menu ' + top;
  await p.mouse.click(+t[1], +t[2]); await sl(2500);
  await run(p, PY([
    'import sys',
    'from PySide6 import QtWidgets',
    'out="none"',
    'for m in QtWidgets.QApplication.topLevelWidgets():',
    '    if isinstance(m, QtWidgets.QMenu) and m.isVisible():',
    '        for a in m.actions():',
    '            t = a.text().replace("&","").strip().lower()',
    '            if t.startswith("' + entry + '") and a.isEnabled():',
    '                g = m.mapToGlobal(m.actionGeometry(a).center())',
    '                if g.y() > 0 and out == "none": out="%d %d"%(g.x(),g.y())',
    'sys.__stderr__.write("ENTRY %s\\n" % out); sys.__stderr__.flush()'
  ]));
  await sl(2200);
  const e = /ENTRY (\d+) (\d+)/.exec(await grab(p, 'ENTRY'));
  if (!e) { await p.keyboard.press('Escape'); return 'no entry "' + entry + '"'; }
  await p.mouse.click(+e[1], +e[2]);
  return 'clicked';
};
(async () => {
  fs.rmSync(DL, { recursive: true, force: true }); fs.mkdirSync(DL, { recursive: true });
  const b = await puppeteer.launch({ executablePath: CHROME, headless: false, defaultViewport: null,
    args: ['--no-sandbox','--use-gl=angle','--use-angle=metal','--window-size=1400,900'],
    protocolTimeout: 900000, userDataDir: '/tmp/fc-filemenu' });
  const p = (await b.pages())[0];
  const errs = []; p.on('pageerror', (e) => errs.push(String(e).split('\n')[0].slice(0,140)));
  const cdp = await p.createCDPSession();
  await cdp.send('Browser.setDownloadBehavior', { behavior: 'allow', downloadPath: DL, eventsEnabled: true });
  await p.goto(process.argv[2] || 'http://localhost:8792/index.html', { waitUntil: 'domcontentloaded', timeout: 300000 });
  const t0 = Date.now();
  while (Date.now() - t0 < 300000) { if (await p.evaluate(() => !!(window.fcInstance && window.fcInstance._malloc))) break; await sl(1000); }
  for (let i=0;i<40;i++){ await sl(3000); await run(p,'import sys,FreeCAD\nsys.__stderr__.write("RDY %d\\n"%len(FreeCAD.__unit_test__))\nsys.__stderr__.flush()\n'); await sl(1200);
    const m=[...(await readLog(p)).matchAll(/RDY (\d+)/g)].pop(); if(m&&+m[1]>0) break; }

  // Chrome prefers showSaveFilePicker, which opens a NATIVE dialog no script can answer --
  // the save then waits on a picker that never resolves. Removing it takes the same
  // fallback path Firefox/Safari users get: an anchor download, which IS observable.
  await p.evaluate(() => { try { delete window.showSaveFilePicker; } catch (e) { window.showSaveFilePicker = undefined; } });
  console.log('showSaveFilePicker removed: ' + await p.evaluate(() => !window.showSaveFilePicker));
  await run(p, PY([
    'import FreeCAD as App, FreeCADGui as Gui',
    'd = App.newDocument("SaveMe")',
    'o = d.addObject("Part::Box","Brick"); o.Length=11; o.Width=12; o.Height=13; d.recompute()',
    'Gui.activateWorkbench("PartWorkbench")',
    'Gui.Selection.clearSelection(); Gui.Selection.addSelection(o)'
  ]));
  await sl(5000);
  const ls = () => fs.existsSync(DL) ? fs.readdirSync(DL).filter((f) => !f.endsWith('.crdownload')) : [];

  const saveClick = await menuClick(p, 'file', 'save');
  await sl(9000);
  console.log(`File > Save (${saveClick}): downloaded ${JSON.stringify(ls())}`);
  // a save dialog may be up (Qt's own or the bridge); report and dismiss
  await run(p, PY([
    'import sys',
    'from PySide6 import QtWidgets',
    'ds = [(type(w).__name__, w.windowTitle()) for w in QtWidgets.QApplication.topLevelWidgets() if isinstance(w, QtWidgets.QDialog) and w.isVisible()]',
    'sys.__stderr__.write("SAVEDLG %s\\n" % ds); sys.__stderr__.flush()'
  ]));
  await sl(2500);
  console.log('  dialog state: ' + await grab(p, 'SAVEDLG'));
  await p.keyboard.press('Escape'); await sl(2000);

  // Export the selected solid (STEP) the same way
  const expClick = await menuClick(p, 'file', 'export');
  await sl(9000);
  console.log(`File > Export (${expClick}): downloaded ${JSON.stringify(ls())}`);
  await run(p, PY([
    'import sys',
    'from PySide6 import QtWidgets',
    'ds = [(type(w).__name__, w.windowTitle()) for w in QtWidgets.QApplication.topLevelWidgets() if isinstance(w, QtWidgets.QDialog) and w.isVisible()]',
    'sys.__stderr__.write("EXPDLG %s\\n" % ds); sys.__stderr__.flush()'
  ]));
  await sl(2500);
  console.log('  dialog state: ' + await grab(p, 'EXPDLG'));
  await p.keyboard.press('Escape'); await sl(2000);

  await run(p, PY([
    'import sys, FreeCAD as App',
    'd = App.getDocument("SaveMe"); d.addObject("Part::Sphere","Alive"); d.recompute()',
    'sys.__stderr__.write("ALIVE %s file=%r\\n" % ([o.Name for o in d.Objects], d.FileName)); sys.__stderr__.flush()'
  ]));
  await sl(3000);
  console.log('after: ' + await grab(p, 'ALIVE'));
  console.log('files on disk: ' + JSON.stringify(ls().map((f) => f + ' ' + fs.statSync(DL + '/' + f).size + 'B')));
  console.log('page errors: ' + (errs.length ? errs.slice(0,3).join(' | ') : 'none'));
  await b.close().catch(()=>{}); process.exit(0);
})().catch((e)=>{console.log('DRIVER '+String(e).slice(0,200));process.exit(0);});
