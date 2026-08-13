// Switch to EVERY workbench by real mouse clicks on the selector, the way a person does.
//
// guisession.js already drove this selector, but it only ever clicked "Part" -- a
// workbench that always worked -- so it reported "switching works" while CAM and OpenSCAD
// were dead on first activation. Clicking all of them, and asserting the ACTIVE workbench
// actually became the one clicked, is the real-input version of wbactivate.js and is what
// would have caught that.
//
// Usage: node scratchpad/wbclick.js [url]
const puppeteer = require('puppeteer-core');
const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
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
    protocolTimeout: 3600000, userDataDir: '/tmp/fc-wbclick' });
  const p = (await b.pages())[0];
  const errs = [];
  p.on('pageerror', (e) => errs.push(String(e).slice(0, 140)));
  await p.goto(URL, { waitUntil: 'domcontentloaded', timeout: 300000 });
  const t0 = Date.now();
  while (Date.now() - t0 < 300000) {
    if (await p.evaluate(() => !!(window.fcInstance && window.fcInstance._malloc))) break;
    await sl(1000);
  }
  for (let i = 0; i < 60; i++) {
    await sl(3000);
    await run(p, 'import sys, FreeCAD\nsys.__stderr__.write("RDY %d\\n" % len(FreeCAD.__unit_test__))\nsys.__stderr__.flush()\n');
    await sl(1200);
    const m = [...(await readLog(p)).matchAll(/RDY (\d+)/g)].pop();
    if (m && +m[1] > 0) break;
  }

  // every entry the selector offers, in its own order
  await run(p, `
import sys
from PySide6 import QtWidgets
import FreeCADGui as Gui
mw = Gui.getMainWindow()
wbtexts = set()
for n in Gui.listWorkbenches():
    try:
        wbtexts.add(Gui.getWorkbench(n).MenuText)
    except Exception:
        pass
def wbcombo():
    for c in mw.findChildren(QtWidgets.QComboBox):
        if not c.isVisible() or c.count() < 3:
            continue
        items = {c.itemText(i) for i in range(c.count())}
        if len(items & wbtexts) >= 3:      # it lists workbenches, whatever else is on screen
            return c
    return None
c = wbcombo()
if c is not None:
    sys.__stderr__.write("WBALL " + "|".join(c.itemText(i) for i in range(c.count())) + "|END\\n")
sys.__stderr__.flush()
`);
  await sl(2000);
  const allm = /WBALL (.*)\|END/.exec(await last(p, /WBALL [^\n]*/g));
  const labels = allm ? allm[1].split('|').filter(Boolean) : [];
  console.log(`PLAN ${labels.length} entries in the selector`);

  let ok = 0, bad = 0, cbSeen = 0;
  for (const label of labels) {
    // <none> provides no toolbars, so selecting it hides the Workbench toolbar itself
    // (FreeCAD's normal behaviour; the user gets back via View > Workbench). Driving a
    // hidden selector afterwards proves nothing -- wbactivate.js covers it via the API.
    if (label.trim() === '<none>') { console.log(`${label.padEnd(22)} skipped (hides its own toolbar)`); continue; }
    // open the popup with a real click on the combo
    await run(p, `
import sys
from PySide6 import QtWidgets, QtCore
import FreeCADGui as Gui
mw = Gui.getMainWindow()
wbtexts = set()
for n in Gui.listWorkbenches():
    try:
        wbtexts.add(Gui.getWorkbench(n).MenuText)
    except Exception:
        pass
for c in mw.findChildren(QtWidgets.QComboBox):
    if not c.isVisible() or c.count() < 3:
        continue
    if len({c.itemText(i) for i in range(c.count())} & wbtexts) < 3:
        continue
    g = c.mapToGlobal(QtCore.QPoint(c.width()//2, c.height()//2))
    sys.__stderr__.write("CB %d %d %s\\n" % (g.x(), g.y(), c.currentText()))
    break
sys.__stderr__.flush()
`);
    await sl(1500);
    const cbLines = ((await readLog(p)).match(/CB \d+[^\n]*/g) || []);
    const cb = cbLines.length > cbSeen ? /CB (\d+) (\d+) (.*)/.exec(cbLines[cbLines.length - 1]) : null;
    cbSeen = cbLines.length;
    if (!cb) { console.log(`${label.padEnd(22)} SELECTOR NOT VISIBLE`); bad++; continue; }
    if (cb[3].trim() === label.trim()) { ok++; console.log(`${label.padEnd(22)} (already active)`); continue; }
    await p.mouse.click(+cb[1], +cb[2]);
    await sl(1500);

    // scrolling is a helper; the click below is a real mouse event on the item's centre
    await run(p, `
import sys
from PySide6 import QtWidgets, QtCore
w = QtWidgets.QApplication.activePopupWidget()
if w is None:
    sys.__stderr__.write("ITEM none\\n")
else:
    v = w.findChild(QtWidgets.QAbstractItemView) or w
    m = v.model()
    for r in range(m.rowCount()):
        i = m.index(r, 0)
        if str(m.data(i)).strip() == ${JSON.stringify(label.trim())}:
            v.scrollTo(i)
            rect = v.visualRect(i)
            c = v.viewport().mapToGlobal(rect.center())
            sys.__stderr__.write("ITEM %d %d\\n" % (c.x(), c.y()))
            break
    else:
        sys.__stderr__.write("ITEM notfound\\n")
sys.__stderr__.flush()
`);
    await sl(1500);
    const it = /ITEM (\d+) (\d+)/.exec(await last(p, /ITEM [^\n]*/g));
    if (!it) { console.log(`${label.padEnd(22)} POPUP MISS`); await p.keyboard.press('Escape'); bad++; continue; }
    await p.mouse.click(+it[1], +it[2]);
    await sl(5000);

    await run(p, 'import sys, FreeCADGui as Gui\n'
      + 'sys.__stderr__.write("NOW %s|%s\\n" % (Gui.activeWorkbench().name(), Gui.activeWorkbench().MenuText))\nsys.__stderr__.flush()\n');
    await sl(1500);
    const now = /NOW ([^|]*)\|([^\n]*)/.exec(await last(p, /NOW [^\n]*/g));
    const got = now ? now[2].trim() : '?';
    if (got === label.trim()) { ok++; console.log(`${label.padEnd(22)} ok`); }
    else { bad++; console.log(`${label.padEnd(22)} DID NOT SWITCH (still ${got})`); }
  }
  console.log(`TOTAL clicked ok=${ok} failed=${bad}`);
  console.log('page errors: ' + (errs.length ? errs.slice(0, 3).join(' | ') : 'none'));
  await p.screenshot({ path: '/tmp/wbclick.png' }).catch(() => {});
  await b.close().catch(() => {}); process.exit(0);
})().catch((e) => { console.log('DRIVER ' + String(e).slice(0, 200)); process.exit(0); });
