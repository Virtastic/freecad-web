// Does the Undo action enable after a real change, given real time for FreeCAD's
// 150 ms activity timer to fire? Two phases with a genuine wait between them --
// processEvents() in a Python loop does not advance wall time, so an in-process probe
// cannot answer this.
const puppeteer = require('puppeteer-core');
const CHROME = process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';  // set CHROME_PATH to run off macOS
const sl = (ms) => new Promise((r) => setTimeout(r, ms));
const run = (p, c) => p.evaluate((c) => { const m = window.fcInstance;
  const n = new TextEncoder().encode(c).length + 1; const q = m._malloc(n); m.stringToUTF8(c, q, n);
  (window.fcRunPy || ((mm, pp) => { mm._fcweb_run_python(pp); mm._free(pp); }))(m, q); }, c);
const tail = async (p, re) => ((await p.evaluate(() => document.getElementById('log').textContent)).match(re) || []).pop() || '(none)';
const CHECK = (tag) => 'import sys\nimport FreeCAD as App, FreeCADGui as Gui\n' +
  'from PySide6 import QtWidgets, QtCore\nmw=Gui.getMainWindow()\n' +
  'e=None\n' +
  'for tb in mw.findChildren(QtWidgets.QToolBar):\n' +
  '    for a in tb.actions():\n' +
  '        if a.text().replace("&","")=="Undo": e=a.isEnabled()\n' +
  't=[c for c in mw.findChildren(QtCore.QTimer) if c.objectName()=="activityTimer"]\n' +
  'd=App.ActiveDocument\n' +
  'sys.__stderr__.write("' + tag + ' undoEnabled=%s undoCount=%s timerActive=%s\\n" % (' +
  'e, getattr(d,"UndoCount","?") if d else "-", t[0].isActive() if t else "?"))\nsys.__stderr__.flush()\n';
(async () => {
  const b = await puppeteer.launch({ executablePath: CHROME, headless: false, defaultViewport: null,
    args: ['--no-sandbox', '--use-gl=angle', '--use-angle=metal', '--window-size=1300,850'],
    protocolTimeout: 1200000, userDataDir: '/tmp/fc-undocheck-' + Date.now() });
  const p = (await b.pages())[0];
  await p.goto('http://localhost:8792/index.html', { waitUntil: 'domcontentloaded', timeout: 300000 });
  const t0 = Date.now();
  while (Date.now() - t0 < 300000) { if (await p.evaluate(() => !!(window.fcInstance && window.fcInstance._malloc))) break; await sl(1000); }
  await sl(17000);
  await run(p, 'import FreeCAD as App\nd=App.newDocument("UC")\n' +
    'd.openTransaction("box")\nd.addObject("Part::Box","B")\nd.commitTransaction()\nd.recompute()\n');
  await sl(1500);
  await run(p, CHECK('UC0')); await sl(1500);
  console.log('right after the change: ' + await tail(p, /UC0 [^\n]*/g));
  await sl(4000);                      // far longer than the 150 ms activity timer
  await run(p, CHECK('UC1')); await sl(1500);
  console.log('4 s later:              ' + await tail(p, /UC1 [^\n]*/g));
  // and after some real user input, which is what normally pumps the loop
  await p.mouse.move(700, 500); await p.mouse.click(700, 500); await sl(3000);
  await run(p, CHECK('UC2')); await sl(1500);
  console.log('after a click in view:  ' + await tail(p, /UC2 [^\n]*/g));
  await b.close().catch(() => {}); process.exit(0);
})().catch((e) => { console.log('DRIVER ' + String(e).slice(0, 200)); process.exit(0); });
