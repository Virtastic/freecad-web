// Does real typing reach Qt at all? (Escape not closing a menu raised the question.)
//
// The Qt canvas has no tabindex and document.activeElement is BODY, so the worry is that
// NO keyboard input reaches Qt -- which would break spreadsheet entry, task-panel fields
// and Sketcher shortcuts, all far more important than Escape. Type into a real
// Spreadsheet cell through a real keyboard and read the value back from the document.
//
// Usage: node scratchpad/typing.js [url]
const puppeteer = require('puppeteer-core');
const CHROME = process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';  // set CHROME_PATH to run off macOS
const sl = (ms) => new Promise((r) => setTimeout(r, ms));
const URL = process.argv[2] || 'http://localhost:8792/index.html';

const run = (p, code) => p.evaluate((c) => {
  const m = window.fcInstance;
  const n = new TextEncoder().encode(c).length + 1; const q = m._malloc(n); m.stringToUTF8(c, q, n);
  (window.fcRunPy || ((mm, pp) => { mm._fcweb_run_python(pp); mm._free(pp); }))(m, q);
}, code);
const readLog = (p) => p.evaluate(() => document.getElementById('log').textContent);
const last = async (p, re) => { const m = (await readLog(p)).match(re) || []; return m.length ? m[m.length - 1] : ''; };

(async () => {
  const b = await puppeteer.launch({ executablePath: CHROME, headless: false, defaultViewport: null,
    args: ['--no-sandbox', '--use-gl=angle', '--use-angle=metal', '--window-size=1400,900'],
    protocolTimeout: 1200000, userDataDir: '/tmp/fc-typing' });
  const p = (await b.pages())[0];
  await p.goto(URL, { waitUntil: 'domcontentloaded', timeout: 300000 });
  const t0 = Date.now();
  while (Date.now() - t0 < 300000) {
    if (await p.evaluate(() => !!(window.fcInstance && window.fcInstance._malloc))) break;
    await sl(1000);
  }
  for (let i = 0; i < 40; i++) {
    await sl(3000);
    await run(p, 'import sys, FreeCAD\nsys.__stderr__.write("RDY %d\\n" % len(FreeCAD.__unit_test__))\nsys.__stderr__.flush()\n');
    await sl(1200);
    const m = [...(await readLog(p)).matchAll(/RDY (\d+)/g)].pop();
    if (m && +m[1] > 0) break;
  }

  // a spreadsheet gives a real Qt cell editor to type into, and a value we can read back
  await run(p, `
import sys
from PySide6 import QtWidgets
import FreeCAD as App, FreeCADGui as Gui
d = App.newDocument("Typing")
sh = d.addObject("Spreadsheet::Sheet", "Sheet")
d.recompute()
Gui.activateWorkbench("SpreadsheetWorkbench")
Gui.Selection.clearSelection()
sh.ViewObject.doubleClicked()      # opens the sheet view, as a user double-clicking it would
sys.__stderr__.write("SHEET ready\\n"); sys.__stderr__.flush()
`);
  await sl(6000);

  // find the sheet's table view and the on-screen centre of cell A1
  await run(p, `
import sys
from PySide6 import QtWidgets, QtCore
import FreeCADGui as Gui
mw = Gui.getMainWindow()
views = [t for t in mw.findChildren(QtWidgets.QTableView) if t.isVisible()]
if not views:
    sys.__stderr__.write("CELL noview\\n")
else:
    v = views[0]
    idx = v.model().index(0, 0)
    v.setCurrentIndex(idx)
    r = v.visualRect(idx)
    g = v.viewport().mapToGlobal(r.center())
    sys.__stderr__.write("CELL %d %d\\n" % (g.x(), g.y()))
sys.__stderr__.flush()
`);
  await sl(2000);
  const cm = /CELL (\d+) (\d+)/.exec(await last(p, /CELL [^\n]*/g));
  if (!cm) { console.log('no visible spreadsheet view: ' + await last(p, /CELL [^\n]*/g)); await b.close(); process.exit(0); }

  await p.mouse.click(+cm[1], +cm[2]);
  await sl(1200);
  await p.keyboard.type('1234');       // real key events
  await sl(800);
  await p.keyboard.press('Enter');
  await sl(2500);

  await run(p, `
import sys, FreeCAD as App
d = App.getDocument("Typing")
sh = d.getObject("Sheet")
try:
    v = sh.get("A1")
except Exception as e:
    v = "EMPTY(%s)" % str(e)[:40]
sys.__stderr__.write("A1 %r\\n" % (v,)); sys.__stderr__.flush()
`);
  await sl(2000);
  console.log('typed 1234 into A1 -> ' + (await last(p, /A1 [^\n]*/g)));

  await p.screenshot({ path: '/tmp/typing.png' }).catch(() => {});
  await b.close().catch(() => {}); process.exit(0);
})().catch((e) => { console.log('DRIVER ' + String(e).slice(0, 200)); process.exit(0); });
