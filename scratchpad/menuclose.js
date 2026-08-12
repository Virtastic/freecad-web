// Can a user dismiss an open menu? Escape, then a click elsewhere. A popup that survives
// both would swallow every later click and would be a launch blocker.
const puppeteer = require('puppeteer-core');
const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const sl = (ms) => new Promise((r) => setTimeout(r, ms));
const run = (p, c) => p.evaluate((c) => { const m = window.fcInstance;
  const n = new TextEncoder().encode(c).length + 1; const q = m._malloc(n); m.stringToUTF8(c, q, n);
  (window.fcRunPy || ((mm, pp) => { mm._fcweb_run_python(pp); mm._free(pp); }))(m, q); }, c);
const tail = async (p, re) => ((await p.evaluate(() => document.getElementById('log').textContent)).match(re) || []).pop() || '(none)';
const Q = (tag) => 'import sys\nfrom PySide6 import QtWidgets\n' +
  'w=QtWidgets.QApplication.activePopupWidget()\n' +
  'a=QtWidgets.QApplication.activeWindow()\n' +
  'sys.__stderr__.write("' + tag + ' popup=%s cls=%s title=%r\\n" % (w is not None, ' +
  'type(w).__name__ if w else "-", w.windowTitle() if w else ""))\nsys.__stderr__.flush()\n';
(async () => {
  const b = await puppeteer.launch({ executablePath: CHROME, headless: false, defaultViewport: null,
    args: ['--no-sandbox', '--use-gl=angle', '--use-angle=metal', '--window-size=1300,850'],
    protocolTimeout: 1200000, userDataDir: '/tmp/fc-menuclose-' + Date.now() });
  const p = (await b.pages())[0];
  await p.goto('http://localhost:8792/index.html', { waitUntil: 'domcontentloaded', timeout: 300000 });
  const t0 = Date.now();
  while (Date.now() - t0 < 300000) { if (await p.evaluate(() => !!(window.fcInstance && window.fcInstance._malloc))) break; await sl(1000); }
  await sl(17000);
  await run(p, 'import FreeCAD as App\nApp.newDocument("MC")\n'); await sl(2000);

  await run(p, Q('MC0')); await sl(1200);
  console.log('at rest:                ' + await tail(p, /MC0 [^\n]*/g));
  // open the View menu (its title sits at a known place on the menu bar)
  await run(p, 'import sys\nimport FreeCADGui as Gui\nfrom PySide6 import QtCore\n' +
    'mb=Gui.getMainWindow().menuBar()\n' +
    'for a in mb.actions():\n' +
    '    if a.text().replace("&","")=="View":\n' +
    '        r=mb.actionGeometry(a); c=mb.mapToGlobal(QtCore.QPoint(r.x()+r.width()//2, r.y()+r.height()//2))\n' +
    '        sys.__stderr__.write("MCP %d %d\\n" % (c.x(), c.y()))\nsys.__stderr__.flush()\n');
  await sl(1500);
  const m = /MCP (\d+) (\d+)/.exec(await tail(p, /MCP [^\n]*/g));
  await p.mouse.click(+m[1], +m[2]); await sl(1800);
  await run(p, Q('MC1')); await sl(1200);
  console.log('after opening View:     ' + await tail(p, /MC1 [^\n]*/g));
  await p.keyboard.press('Escape'); await sl(1500);
  await run(p, Q('MC2')); await sl(1200);
  console.log('after one Escape:       ' + await tail(p, /MC2 [^\n]*/g));
  await p.mouse.click(700, 600); await sl(1800);              // click in the 3D view
  await run(p, Q('MC3')); await sl(1200);
  console.log('after clicking the view:' + await tail(p, /MC3 [^\n]*/g));
  // and can we still drive the app afterwards?
  await run(p, 'import FreeCAD as App\nd=App.ActiveDocument\nd.addObject("Part::Box","After")\nd.recompute()\n');
  await sl(2000);
  await run(p, 'import sys, FreeCAD as App\nsys.__stderr__.write("MC4 objs=%d\\n" % len(App.ActiveDocument.Objects))\nsys.__stderr__.flush()\n');
  await sl(1200);
  console.log('app still usable:       ' + await tail(p, /MC4 [^\n]*/g));
  await b.close().catch(() => {}); process.exit(0);
})().catch((e) => { console.log('DRIVER ' + String(e).slice(0, 200)); process.exit(0); });
