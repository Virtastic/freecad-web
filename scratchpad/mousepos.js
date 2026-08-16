// What position does Qt receive for a mouse click in the 3D view?
// Drawing a sketch line by clicking produced a line with BOTH ends at (0,0), so either
// the sketcher unprojects wrongly or the events arrive without usable coordinates.
const puppeteer = require('puppeteer-core');
const CHROME = process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';  // set CHROME_PATH to run off macOS
const sl = (ms) => new Promise((r) => setTimeout(r, ms));
const run = (p, code) => p.evaluate((c) => {
  const m = window.fcInstance;
  const n = new TextEncoder().encode(c).length + 1; const q = m._malloc(n); m.stringToUTF8(c, q, n);
  (window.fcRunPy || ((mm, pp) => { mm._fcweb_run_python(pp); mm._free(pp); }))(m, q);
}, code);
const readLog = (p) => p.evaluate(() => document.getElementById('log').textContent);
(async () => {
  const b = await puppeteer.launch({ executablePath: CHROME, headless: false, defaultViewport: null,
    args: ['--no-sandbox','--use-gl=angle','--use-angle=metal','--window-size=1400,900'],
    protocolTimeout: 1200000, userDataDir: '/tmp/fc-mpos' });
  const p = (await b.pages())[0];
  await p.goto('http://localhost:8792/index.html', { waitUntil: 'domcontentloaded', timeout: 300000 });
  const t0 = Date.now();
  while (Date.now() - t0 < 300000) { if (await p.evaluate(() => !!(window.fcInstance && window.fcInstance._malloc))) break; await sl(1000); }
  for (let i=0;i<40;i++){ await sl(3000); await run(p,'import sys,FreeCAD\nsys.__stderr__.write("RDY %d\\n"%len(FreeCAD.__unit_test__))\nsys.__stderr__.flush()\n'); await sl(1200);
    const m=[...(await readLog(p)).matchAll(/RDY (\d+)/g)].pop(); if(m&&+m[1]>0) break; }
  await run(p, `
import sys
import FreeCAD as App, FreeCADGui as Gui
d = App.newDocument("MPos"); d.addObject("Part::Box","Box"); d.recompute()
Gui.SendMsgToActiveView("ViewFit")
sys.__stderr__.write("DOC ok\\n"); sys.__stderr__.flush()
`);
  await sl(5000);
  // filter mouse events on the 3D view widget and report their positions
  await run(p, `
import sys
from PySide6 import QtWidgets, QtCore
import FreeCADGui as Gui
mdi = Gui.getMainWindow().findChild(QtWidgets.QMdiArea)
sub = mdi.currentSubWindow()
class Spy(QtCore.QObject):
    def eventFilter(self, o, e):
        t = e.type()
        if t in (QtCore.QEvent.MouseButtonPress, QtCore.QEvent.MouseMove):
            try:
                pos = e.position()
                sys.__stderr__.write("MEV %s cls=%s pos=(%.0f,%.0f)\\n" % (
                    "press" if t == QtCore.QEvent.MouseButtonPress else "move",
                    o.__class__.__name__, pos.x(), pos.y()))
                sys.__stderr__.flush()
            except Exception as ex:
                sys.__stderr__.write("MEV err %s\\n" % ex); sys.__stderr__.flush()
        return False
spy = Spy(sub)
for w in [sub] + sub.findChildren(QtWidgets.QWidget):
    w.installEventFilter(spy)
Gui.getMainWindow()._mposSpy = spy
c = sub.mapToGlobal(QtCore.QPoint(sub.width()//2, sub.height()//2))
sys.__stderr__.write("CENTRE %d %d size=%dx%d\\n" % (c.x(), c.y(), sub.width(), sub.height()))
sys.__stderr__.flush()
`);
  await sl(2500);
  const cm = /CENTRE (\d+) (\d+) size=(\d+)x(\d+)/.exec((await readLog(p)).match(/CENTRE [^\n]*/g).pop());
  const cx=+cm[1], cy=+cm[2];
  console.log('view centre at screen ' + cx + ',' + cy + ' size ' + cm[3] + 'x' + cm[4]);
  await p.mouse.move(cx - 100, cy - 50); await sl(900);
  await p.mouse.click(cx - 100, cy - 50); await sl(1800);
  const evs = ((await readLog(p)).match(/MEV [^\n]*/g) || []);
  console.log('Qt mouse events seen: ' + (evs.length ? evs.slice(-6).join(' | ') : 'NONE'));
  console.log('  (clicked 100 left / 50 up of centre, so a correct local pos is offset from the widget middle)');
  await b.close().catch(()=>{}); process.exit(0);
})().catch((e)=>{console.log('DRIVER '+String(e).slice(0,200));process.exit(0);});
