const puppeteer = require('puppeteer-core');
const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
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
    protocolTimeout: 1200000, userDataDir: '/tmp/fc-mods' });
  const p = (await b.pages())[0];
  await p.goto('http://localhost:8792/index.html', { waitUntil: 'domcontentloaded', timeout: 300000 });
  const t0 = Date.now();
  while (Date.now() - t0 < 300000) { if (await p.evaluate(() => !!(window.fcInstance && window.fcInstance._malloc))) break; await sl(1000); }
  for (let i=0;i<40;i++){ await sl(3000); await run(p,'import sys,FreeCAD\nsys.__stderr__.write("RDY %d\\n"%len(FreeCAD.__unit_test__))\nsys.__stderr__.flush()\n'); await sl(1200);
    const m=[...(await readLog(p)).matchAll(/RDY (\d+)/g)].pop(); if(m&&+m[1]>0) break; }

  // what does the DOM see, and what does Qt see, for the same Ctrl+A?
  await p.evaluate(() => {
    window.__domKeys = [];
    window.addEventListener('keydown', (e) => {
      window.__domKeys.push(e.key + ' ctrl=' + e.ctrlKey + ' meta=' + e.metaKey);
    }, true);
  });
  await run(p, `
import sys
from PySide6 import QtWidgets, QtCore
import FreeCADGui as Gui
mw = Gui.getMainWindow()
le = QtWidgets.QLineEdit(mw); le.setObjectName("modProbe")
le.setGeometry(60, 120, 260, 34); le.show(); le.raise_(); le.setFocus(QtCore.Qt.OtherFocusReason)
class Spy(QtCore.QObject):
    def eventFilter(self, o, e):
        if e.type() == QtCore.QEvent.KeyPress:
            sys.__stderr__.write("QTKEY key=%d mods=%d text=%r\\n" % (e.key(), int(e.modifiers().value), e.text()))
            sys.__stderr__.flush()
        return False
spy = Spy(le); le.installEventFilter(spy); mw._modSpy = spy
g = le.mapToGlobal(QtCore.QPoint(le.width()//2, le.height()//2))
sys.__stderr__.write("PROBE %d %d\\n" % (g.x(), g.y())); sys.__stderr__.flush()
`);
  await sl(2500);
  const pr = /PROBE (\d+) (\d+)/.exec((await readLog(p)).match(/PROBE [^\n]*/g).pop());
  await p.mouse.click(+pr[1], +pr[2]);
  await sl(800);
  await p.keyboard.down('Control'); await p.keyboard.press('KeyA'); await p.keyboard.up('Control');
  await sl(1500);
  await p.keyboard.down('Control'); await p.keyboard.press('KeyZ'); await p.keyboard.up('Control');
  await sl(1500);
  const log = await readLog(p);
  console.log('Qt saw: ' + ((log.match(/QTKEY [^\n]*/g)||[]).join(' | ') || 'NOTHING'));
  console.log('DOM saw: ' + JSON.stringify(await p.evaluate(() => window.__domKeys)));
  // Qt::ControlModifier == 0x04000000 == 67108864
  await run(p, 'import sys\nfrom PySide6 import QtWidgets\nimport FreeCADGui as Gui\n'
    + 'w=Gui.getMainWindow().findChild(QtWidgets.QLineEdit,"modProbe")\n'
    + 'sys.__stderr__.write("FINAL %r\\n" % (w.text() if w else None))\n'
    + '\nif w: w.deleteLater()\nsys.__stderr__.flush()\n');
  await sl(1500);
  console.log('field text: ' + ((await readLog(p)).match(/FINAL [^\n]*/g)||['?']).pop());
  await b.close().catch(()=>{}); process.exit(0);
})().catch((e)=>{console.log('DRIVER '+String(e).slice(0,200));process.exit(0);});
