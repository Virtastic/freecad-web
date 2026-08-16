// Is the Undo toolbar click landing on the button's dropdown arrow instead of its action?
const puppeteer = require('puppeteer-core');
const CHROME = process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';  // set CHROME_PATH to run off macOS
const sl = (ms) => new Promise((r) => setTimeout(r, ms));
const run = (p, c) => p.evaluate((c) => { const m = window.fcInstance;
  const n = new TextEncoder().encode(c).length + 1; const q = m._malloc(n); m.stringToUTF8(c, q, n);
  (window.fcRunPy || ((mm, pp) => { mm._fcweb_run_python(pp); mm._free(pp); }))(m, q); }, c);
const tail = async (p, re) => ((await p.evaluate(() => document.getElementById('log').textContent)).match(re) || []).pop() || '(none)';
const GEOM = 'import sys\nimport FreeCADGui as Gui\nfrom PySide6 import QtWidgets, QtCore\n' +
  'mw=Gui.getMainWindow()\n' +
  'for tb in mw.findChildren(QtWidgets.QToolBar):\n' +
  '    for a in tb.actions():\n' +
  '        if a.text().replace("&","")=="Undo":\n' +
  '            w=tb.widgetForAction(a)\n' +
  '            g=w.geometry(); tl=w.mapToGlobal(QtCore.QPoint(0,0))\n' +
  '            sys.__stderr__.write("UG rect=%d,%d %dx%d enabled=%s popupMode=%s\\n" % (\n' +
  '                tl.x(), tl.y(), g.width(), g.height(), a.isEnabled(),\n' +
  '                getattr(w, "popupMode", lambda: "n/a")()))\n' +
  'sys.__stderr__.flush()\n';
const STATE = 'import sys, FreeCAD as App\nfrom PySide6 import QtWidgets\n' +
  'd=App.ActiveDocument\np=QtWidgets.QApplication.activePopupWidget()\n' +
  'sys.__stderr__.write("US objs=%d undo=%s popup=%s\\n" % (len(d.Objects), d.UndoCount, p is not None))\nsys.__stderr__.flush()\n';
(async () => {
  const b = await puppeteer.launch({ executablePath: CHROME, headless: false, defaultViewport: null,
    args: ['--no-sandbox', '--use-gl=angle', '--use-angle=metal', '--window-size=1300,850'],
    protocolTimeout: 1200000, userDataDir: '/tmp/fc-undoclick-' + Date.now() });
  const p = (await b.pages())[0];
  await p.goto('http://localhost:8792/index.html', { waitUntil: 'domcontentloaded', timeout: 300000 });
  const t0 = Date.now();
  while (Date.now() - t0 < 300000) { if (await p.evaluate(() => !!(window.fcInstance && window.fcInstance._malloc))) break; await sl(1000); }
  await sl(17000);
  await run(p, 'import FreeCAD as App\nd=App.newDocument("UK")\nd.openTransaction("box")\n' +
    'd.addObject("Part::Box","B")\nd.commitTransaction()\nd.recompute()\n');
  await sl(3500);
  await run(p, GEOM); await sl(1500);
  const g = await tail(p, /UG [^\n]*/g);
  console.log('undo button: ' + g);
  const m = /rect=(\d+),(\d+) (\d+)x(\d+)/.exec(g);
  await run(p, STATE); await sl(1200);
  console.log('before: ' + await tail(p, /US [^\n]*/g));
  if (m) {
    const [x, y, w, h] = [+m[1], +m[2], +m[3], +m[4]];
    // left third: the action area, well clear of any dropdown arrow on the right
    await p.mouse.click(x + Math.round(w * 0.25), y + Math.round(h / 2));
    await sl(3000);
    await run(p, STATE); await sl(1200);
    console.log('after left-third click: ' + await tail(p, /US [^\n]*/g));
  }
  await b.close().catch(() => {}); process.exit(0);
})().catch((e) => { console.log('DRIVER ' + String(e).slice(0, 200)); process.exit(0); });
