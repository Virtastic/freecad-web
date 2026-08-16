// Right-click context menus, driven by real mouse input.
//
// These were converted from QMenu::exec() (which deadlocks single-threaded Qt-wasm) to
// heap+popup() a while back, but verified through Python. Popups have since proven to
// behave unusually on this build -- they never get the keyboard grab -- so the menus a
// user actually opens with the right mouse button are worth exercising directly.
//
// Usage: node scratchpad/ctxmenu.js [url]
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
    protocolTimeout: 1200000, userDataDir: '/tmp/fc-ctx' });
  const p = (await b.pages())[0];
  const errs = [];
  p.on('pageerror', (e) => errs.push(String(e).slice(0, 140)));
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

  await run(p, `
import sys
import FreeCAD as App, FreeCADGui as Gui
d = App.newDocument("Ctx")
d.addObject("Part::Box", "Box")
d.recompute()
Gui.activateWorkbench("PartWorkbench")
Gui.SendMsgToActiveView("ViewFit")
sys.__stderr__.write("DOC ready\\n"); sys.__stderr__.flush()
`);
  await sl(5000);

  // the model tree lays out OFF-SCREEN until the Model tab is clicked (known trap)
  await run(p, `
import sys
from PySide6 import QtWidgets, QtCore
import FreeCADGui as Gui
mw = Gui.getMainWindow()
for tb in mw.findChildren(QtWidgets.QTabBar):
    for i in range(tb.count()):
        if tb.tabText(i).strip().lower() == "model":
            g = tb.mapToGlobal(tb.tabRect(i).center())
            sys.__stderr__.write("TAB %d %d\\n" % (g.x(), g.y()))
            break
sys.__stderr__.flush()
`);
  await sl(1800);
  const tab = /TAB (\d+) (\d+)/.exec(await last(p, /TAB [^\n]*/g));
  if (tab) { await p.mouse.click(+tab[1], +tab[2]); await sl(2500); }

  const popup = async (tag) => {
    await run(p, `
import sys
from PySide6 import QtWidgets
w = QtWidgets.QApplication.activePopupWidget()
if w is None:
    sys.__stderr__.write("PU ${tag} none\\n")
else:
    acts = [a.text().replace("&","") for a in w.actions() if a.text()]
    sys.__stderr__.write("PU ${tag} %s items=%d %s\\n" % (w.__class__.__name__, len(acts), acts[:5]))
sys.__stderr__.flush()
`);
    await sl(1600);
    return (await last(p, new RegExp('PU ' + tag + ' [^\\n]*', 'g'))).replace('PU ' + tag + ' ', '');
  };

  // 1. right-click a tree item
  await run(p, `
import sys
from PySide6 import QtWidgets, QtCore
import FreeCADGui as Gui
mw = Gui.getMainWindow()
best = None
for t in mw.findChildren(QtWidgets.QTreeWidget) + mw.findChildren(QtWidgets.QTreeView):
    if not t.isVisible():
        continue
    m = t.model()
    if m is None or m.rowCount() == 0:
        continue
    idx = m.index(0, 0)
    r = t.visualRect(idx)
    if r.isValid() and r.width() > 0:
        g = t.viewport().mapToGlobal(r.center())
        if g.x() > 0 and g.y() > 0:
            best = (g.x(), g.y(), str(m.data(idx)))
            break
sys.__stderr__.write("TREE %s\\n" % (("%d %d %s" % best) if best else "notfound"))
sys.__stderr__.flush()
`);
  await sl(1800);
  const tr = /TREE (\d+) (\d+) (.*)/.exec(await last(p, /TREE [^\n]*/g));
  if (tr) {
    await p.mouse.click(+tr[1], +tr[2], { button: 'right' });
    await sl(3000);
    console.log(`tree right-click on "${tr[3].trim()}": ${await popup('T')}`);
    await p.keyboard.press('Escape');        // uses the Escape fix
    await sl(2000);
    console.log('  after Escape: ' + await popup('T2'));
  } else {
    console.log('tree item not found: ' + (await last(p, /TREE [^\n]*/g)));
  }

  // 2. right-click in the 3D view
  await run(p, `
import sys
from PySide6 import QtWidgets, QtCore
import FreeCADGui as Gui
mdi = Gui.getMainWindow().findChild(QtWidgets.QMdiArea)
sub = mdi.currentSubWindow() if mdi else None
if sub is None:
    sys.__stderr__.write("VIEW none\\n")
else:
    g = sub.mapToGlobal(QtCore.QPoint(sub.width()//2, sub.height()//2))
    sys.__stderr__.write("VIEW %d %d\\n" % (g.x(), g.y()))
sys.__stderr__.flush()
`);
  await sl(1800);
  const vw = /VIEW (\d+) (\d+)/.exec(await last(p, /VIEW [^\n]*/g));
  if (vw) {
    await p.mouse.click(+vw[1], +vw[2], { button: 'right' });
    await sl(3500);
    console.log('3D view right-click: ' + await popup('V'));
    await p.keyboard.press('Escape');
    await sl(2000);
    console.log('  after Escape: ' + await popup('V2'));
  } else {
    console.log('3D view not found');
  }

  console.log('page errors: ' + (errs.length ? errs.slice(0, 3).join(' | ') : 'none'));
  await p.screenshot({ path: '/tmp/ctxmenu.png' }).catch(() => {});
  await b.close().catch(() => {}); process.exit(0);
})().catch((e) => { console.log('DRIVER ' + String(e).slice(0, 200)); process.exit(0); });
