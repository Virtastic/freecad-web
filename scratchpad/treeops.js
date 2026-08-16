// Everyday tree operations with real keyboard/mouse: delete, rename, copy/paste.
// Among the most-used interactions in the app and none had been driven by real input.
const puppeteer = require('puppeteer-core');
const CHROME = process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';  // set CHROME_PATH to run off macOS
const sl = (ms) => new Promise((r) => setTimeout(r, ms));
const URL = process.argv[2] || 'http://localhost:8792/index.html';
const MOD = process.platform === 'darwin' ? 'Meta' : 'Control';
const run = (p, code) => p.evaluate((c) => {
  const m = window.fcInstance;
  const n = new TextEncoder().encode(c).length + 1; const q = m._malloc(n); m.stringToUTF8(c, q, n);
  (window.fcRunPy || ((mm, pp) => { mm._fcweb_run_python(pp); mm._free(pp); }))(m, q);
}, code);
const readLog = (p) => p.evaluate(() => document.getElementById('log').textContent);
const last = async (p, re) => { const m = (await readLog(p)).match(re) || []; return m.length ? m[m.length-1] : ''; };

(async () => {
  const b = await puppeteer.launch({ executablePath: CHROME, headless: false, defaultViewport: null,
    args: ['--no-sandbox','--use-gl=angle','--use-angle=metal','--window-size=1400,900'],
    protocolTimeout: 1800000, userDataDir: '/tmp/fc-treeops2' });
  const p = (await b.pages())[0];
  const errs = []; p.on('pageerror', (e) => errs.push(String(e).slice(0,120)));
  await p.goto(URL, { waitUntil: 'domcontentloaded', timeout: 300000 });
  const t0 = Date.now();
  while (Date.now() - t0 < 300000) { if (await p.evaluate(() => !!(window.fcInstance && window.fcInstance._malloc))) break; await sl(1000); }
  for (let i=0;i<40;i++){ await sl(3000); await run(p,'import sys,FreeCAD\nsys.__stderr__.write("RDY %d\\n"%len(FreeCAD.__unit_test__))\nsys.__stderr__.flush()\n'); await sl(1200);
    const m=[...(await readLog(p)).matchAll(/RDY (\d+)/g)].pop(); if(m&&+m[1]>0) break; }

  await run(p, `
import sys
import FreeCAD as App, FreeCADGui as Gui
d = App.newDocument("Tree")
for n, L in (("Alpha", 10), ("Beta", 20)):
    b = d.addObject("Part::Box", n); b.Length = L; b.Width = L; b.Height = L
d.recompute(); Gui.SendMsgToActiveView("ViewFit")
sys.__stderr__.write("SETUP %s\\n" % [o.Name for o in d.Objects]); sys.__stderr__.flush()
`);
  await sl(4000);
  console.log(await last(p, /SETUP [^\n]*/g));

  // the tree lays out off-screen until the Model tab is clicked
  await run(p, `
import sys
from PySide6 import QtWidgets
import FreeCADGui as Gui
mw = Gui.getMainWindow()
for tb in mw.findChildren(QtWidgets.QTabBar):
    for i in range(tb.count()):
        if tb.tabText(i).strip().lower() == "model":
            g = tb.mapToGlobal(tb.tabRect(i).center())
            sys.__stderr__.write("TAB %d %d\\n" % (g.x(), g.y()))
sys.__stderr__.flush()
`);
  await sl(1800);
  const tab = /TAB (\d+) (\d+)/.exec(await last(p, /TAB [^\n]*/g));
  if (tab) { await p.mouse.click(+tab[1], +tab[2]); await sl(2500); }

  const findItem = async (label) => {
    await run(p, `
import sys
from PySide6 import QtWidgets, QtCore
import FreeCADGui as Gui
mw = Gui.getMainWindow()
found = None
for t in mw.findChildren(QtWidgets.QTreeWidget) + mw.findChildren(QtWidgets.QTreeView):
    if not t.isVisible(): continue
    m = t.model()
    if m is None: continue
    hits = m.match(m.index(0,0), QtCore.Qt.DisplayRole, ${JSON.stringify(label)}, 1,
                   QtCore.Qt.MatchRecursive | QtCore.Qt.MatchExactly)
    if hits:
        t.scrollTo(hits[0]); r = t.visualRect(hits[0])
        g = t.viewport().mapToGlobal(r.center())
        if g.x() > 0 and g.y() > 0: found = (g.x(), g.y()); break
sys.__stderr__.write("ITEM %s\\n" % (("%d %d" % found) if found else "notfound")); sys.__stderr__.flush()
`);
    await sl(1600);
    return /ITEM (\d+) (\d+)/.exec(await last(p, /ITEM [^\n]*/g));
  };
  const names = async (tag) => {
    await run(p, `
import sys, FreeCAD as App
d = App.getDocument("Tree")
sys.__stderr__.write("NAMES ${tag} %s | labels %s\\n" % ([o.Name for o in d.Objects], [o.Label for o in d.Objects]))
sys.__stderr__.flush()
`);
    await sl(1600);
    return (await last(p, new RegExp('NAMES ' + tag + ' [^\\n]*', 'g'))).replace('NAMES ' + tag + ' ', '');
  };

  // 1. copy/paste an object with the keyboard
  const selState = async (tag) => {
    await run(p, `
import sys
from PySide6 import QtWidgets
import FreeCADGui as Gui
sel = [o.Name for o in Gui.Selection.getSelection()]
fw = QtWidgets.QApplication.focusWidget()
sys.__stderr__.write("SEL ${'${tag}'} %s focus=%s\\n" % (sel, fw.__class__.__name__ if fw else None))
sys.__stderr__.flush()
`);
    await sl(1600);
    return (await last(p, new RegExp('SEL ' + tag + ' [^\\n]*', 'g'))).replace('SEL ' + tag + ' ', '');
  };

  let it = await findItem('Alpha');
  if (it) {
    await p.mouse.click(+it[1], +it[2]); await sl(1500);
    console.log('  after clicking Alpha: ' + await selState('A'));
    await p.keyboard.down(MOD); await p.keyboard.press('KeyC'); await p.keyboard.up(MOD); await sl(1500);
    await p.keyboard.down(MOD); await p.keyboard.press('KeyV'); await p.keyboard.up(MOD); await sl(3000);
    console.log('after copy/paste: ' + await names('A'));
  } else { console.log('copy/paste: tree item Alpha not found'); }

  // 2. delete with the Delete key
  it = await findItem('Beta');
  if (it) {
    await p.mouse.click(+it[1], +it[2]); await sl(1500);
    console.log('  after clicking Beta : ' + await selState('B'));
    await p.keyboard.press('Delete'); await sl(3000);
    console.log('after Delete key : ' + await names('B'));
  } else { console.log('delete: tree item Beta not found'); }

  // 3. undo the delete with the keyboard
  await p.keyboard.down(MOD); await p.keyboard.press('KeyZ'); await p.keyboard.up(MOD); await sl(3000);
  console.log('after undo       : ' + await names('C'));

  console.log('page errors: ' + (errs.length ? errs.slice(0,3).join(' | ') : 'none'));
  await p.screenshot({ path: '/tmp/treeops.png' }).catch(()=>{});
  await b.close().catch(()=>{}); process.exit(0);
})().catch((e)=>{console.log('DRIVER '+String(e).slice(0,200));process.exit(0);});
