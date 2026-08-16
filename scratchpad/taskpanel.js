// Drive a PartDesign Pad through its TASK PANEL with real mouse and keyboard.
//
// Modelling has only ever been driven through Python here (workflows.js), and this
// session's defects were all "the scripted path works, the clicked path does not". The
// task panel is the main modelling surface: a command puts a form in the left dock, the
// user types a value and presses OK, and geometry appears. Nothing had exercised that.
//
// Usage: node scratchpad/taskpanel.js [url]
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
    protocolTimeout: 1200000, userDataDir: '/tmp/fc-task3' });
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

  // a Body with a closed sketch, ready to pad -- the setup, not the thing under test
  await run(p, `
import sys
import FreeCAD as App, FreeCADGui as Gui, Part, Sketcher
d = App.newDocument("TaskPad")
Gui.activateWorkbench("PartDesignWorkbench")
body = d.addObject("PartDesign::Body", "Body")
sk = d.addObject("Sketcher::SketchObject", "Sketch")
body.addObject(sk)
sk.addGeometry(Part.LineSegment(App.Vector(0,0,0), App.Vector(20,0,0)), False)
sk.addGeometry(Part.LineSegment(App.Vector(20,0,0), App.Vector(20,20,0)), False)
sk.addGeometry(Part.LineSegment(App.Vector(20,20,0), App.Vector(0,20,0)), False)
sk.addGeometry(Part.LineSegment(App.Vector(0,20,0), App.Vector(0,0,0)), False)
for i in range(4):
    sk.addConstraint(Sketcher.Constraint('Coincident', i, 2, (i+1) % 4, 1))
d.recompute()
Gui.Selection.clearSelection()
Gui.Selection.addSelection(d.Name, sk.Name)
sys.__stderr__.write("SETUP body=%s sketch=%s\\n" % (body.Name, sk.Name)); sys.__stderr__.flush()
`);
  await sl(4000);

  // invoke Pad the way the toolbar does, then drive the PANEL by hand
  await run(p, 'import sys, FreeCADGui as Gui\nGui.runCommand("PartDesign_Pad", 0)\n'
    + 'sys.__stderr__.write("PAD invoked\\n"); sys.__stderr__.flush()\n');
  await sl(5000);

  // the panel's length field: find the focused/first QDoubleSpinBox in the task dock
  await run(p, `
import sys
from PySide6 import QtWidgets, QtCore
import FreeCADGui as Gui
mw = Gui.getMainWindow()
boxes = [w for w in mw.findChildren(QtWidgets.QAbstractSpinBox) if w.isVisible()]
sys.__stderr__.write("PANEL spinboxes=%d\\n" % len(boxes))
if boxes:
    w = boxes[0]
    g = w.mapToGlobal(QtCore.QPoint(w.width()//2, w.height()//2))
    sys.__stderr__.write("FIELD %d %d %r\\n" % (g.x(), g.y(), w.text()))
# the OK button lives in the task panel's button box
oks = [x for x in mw.findChildren(QtWidgets.QPushButton) if x.isVisible() and x.text().replace("&","") in ("OK","Ok")]
if oks:
    o = oks[0]
    g = o.mapToGlobal(QtCore.QPoint(o.width()//2, o.height()//2))
    sys.__stderr__.write("OK %d %d\\n" % (g.x(), g.y()))
else:
    sys.__stderr__.write("OK none\\n")
sys.__stderr__.flush()
`);
  await sl(2500);
  console.log((await last(p, /PANEL [^\n]*/g)) || 'no panel line');
  const fld = /FIELD (\d+) (\d+) (.*)/.exec(await last(p, /FIELD [^\n]*/g));
  const okb = /OK (\d+) (\d+)/.exec(await last(p, /OK [^\n]*/g));
  if (!fld || !okb) {
    console.log('INCONCLUSIVE: task panel field or OK button not found (field=' + !!fld + ' ok=' + !!okb + ')');
    await p.screenshot({ path: '/tmp/taskpanel.png' }).catch(() => {});
    await b.close().catch(() => {}); process.exit(0);
  }
  console.log('length field showed ' + fld[3]);

  // type a real length, and CHECK THE FIELD before committing: "the pad came out 10"
  // does not say whether the keystrokes missed the widget or merely failed to commit.
  await p.mouse.click(+fld[1], +fld[2]);
  await sl(600);
  // select-all is Cmd+A on macOS: Qt maps the physical Control key to MetaModifier there
  // and Cmd to ControlModifier, so Ctrl+A correctly types a literal 'a' (verified with an
  // event filter: Ctrl -> mods=0x10000000 Meta, Cmd -> mods=0x04000000 Control).
  const SELECT_ALL = process.platform === 'darwin' ? 'Meta' : 'Control';
  await p.keyboard.down(SELECT_ALL); await p.keyboard.press('KeyA'); await p.keyboard.up(SELECT_ALL);
  await sl(400);
  await p.keyboard.type('7');
  await sl(900);
  await run(p, `
import sys
from PySide6 import QtWidgets
import FreeCADGui as Gui
bs = [w for w in Gui.getMainWindow().findChildren(QtWidgets.QAbstractSpinBox) if w.isVisible()]
sys.__stderr__.write("AFTERTYPE %r focus=%s\\n" % (bs[0].text() if bs else None,
                                                  bs[0].hasFocus() if bs else "-"))
sys.__stderr__.flush()
`);
  await sl(2000);
  console.log('field after typing 7: ' + (await last(p, /AFTERTYPE [^\n]*/g)));

  await p.keyboard.press('Tab');    // commit the editor the way a user tabbing out would
  await sl(1200);
  await p.mouse.click(+okb[1], +okb[2]);
  await sl(6000);

  await run(p, `
import sys
import FreeCAD as App
d = App.getDocument("TaskPad")
pads = [o for o in d.Objects if o.TypeId == "PartDesign::Pad"]
if not pads:
    sys.__stderr__.write("RESULT no pad created\\n")
else:
    pad = pads[0]
    sh = getattr(pad, "Shape", None)
    sys.__stderr__.write("RESULT pad Length=%s volume=%s\\n" % (
        pad.Length, ("%.1f" % sh.Volume) if sh is not None and not sh.isNull() else "none"))
sys.__stderr__.flush()
`);
  await sl(2500);
  console.log((await last(p, /RESULT [^\n]*/g)) || 'no result line');
  console.log('  (20 x 20 sketch padded 7 mm should be 2800)');
  console.log('page errors: ' + (errs.length ? errs.slice(0, 3).join(' | ') : 'none'));
  await p.screenshot({ path: '/tmp/taskpanel.png' }).catch(() => {});
  await b.close().catch(() => {}); process.exit(0);
})().catch((e) => { console.log('DRIVER ' + String(e).slice(0, 200)); process.exit(0); });
