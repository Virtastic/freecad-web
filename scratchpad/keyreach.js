// Do real key events reach Qt at all?
//
// A spreadsheet cell not accepting typed text could be edit semantics; a focused QLineEdit
// cannot be. This is the instrument that separates "keyboard input is broken" (which would
// make the app unusable for real work) from "one widget needs a different gesture".
//
// Usage: node scratchpad/keyreach.js [url]
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
    protocolTimeout: 1200000, userDataDir: '/tmp/fc-keyreach' });
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

  // a plain focused QLineEdit inside the main window
  await run(p, `
import sys
from PySide6 import QtWidgets, QtCore
import FreeCADGui as Gui
mw = Gui.getMainWindow()
le = QtWidgets.QLineEdit(mw)
le.setObjectName("fcwebKeyProbe")
le.setGeometry(60, 120, 260, 34)
le.show(); le.raise_(); le.setFocus(QtCore.Qt.OtherFocusReason)
g = le.mapToGlobal(QtCore.QPoint(le.width()//2, le.height()//2))
sys.__stderr__.write("LE %d %d focus=%s\\n" % (g.x(), g.y(), le.hasFocus()))
sys.__stderr__.flush()
`);
  await sl(2500);
  const le = /LE (\d+) (\d+) focus=(\w+)/.exec(await last(p, /LE [^\n]*/g));
  if (!le) { console.log('probe field not created'); await b.close(); process.exit(0); }
  console.log('QLineEdit created, hasFocus=' + le[3]);

  // click it (so Qt's own focus handling runs), then type real keys
  await p.mouse.click(+le[1], +le[2]);
  await sl(1000);
  await p.keyboard.type('hello42');
  await sl(1500);

  await run(p, `
import sys
from PySide6 import QtWidgets
import FreeCADGui as Gui
le = Gui.getMainWindow().findChild(QtWidgets.QLineEdit, "fcwebKeyProbe")
sys.__stderr__.write("TEXT %r focus=%s\\n" % (le.text() if le else None, le.hasFocus() if le else "-"))
sys.__stderr__.flush()
`);
  await sl(1800);
  console.log('after typing "hello42": ' + (await last(p, /TEXT [^\n]*/g)));

  // and does Escape reach a widget that is definitely focused?
  await run(p, `
import sys
from PySide6 import QtWidgets, QtCore
import FreeCADGui as Gui
le = Gui.getMainWindow().findChild(QtWidgets.QLineEdit, "fcwebKeyProbe")
class Spy(QtCore.QObject):
    def eventFilter(self, o, e):
        if e.type() == QtCore.QEvent.KeyPress:
            sys.__stderr__.write("KEYPRESS %s\\n" % e.key()); sys.__stderr__.flush()
        return False
spy = Spy(le); le.installEventFilter(spy)
Gui.getMainWindow()._fcwebSpy = spy
sys.__stderr__.write("SPY installed\\n"); sys.__stderr__.flush()
`);
  await sl(1500);
  await p.keyboard.press('KeyZ');
  await sl(1200);
  await p.keyboard.press('Escape');
  await sl(1500);
  const keys = ((await readLog(p)).match(/KEYPRESS \d+/g) || []);
  console.log('key presses Qt saw on the focused field: ' + (keys.length ? keys.join(', ') : 'NONE'));

  await run(p, `
import sys
from PySide6 import QtWidgets
import FreeCADGui as Gui
le = Gui.getMainWindow().findChild(QtWidgets.QLineEdit, "fcwebKeyProbe")
if le: le.deleteLater()
sys.__stderr__.write("CLEANED\\n"); sys.__stderr__.flush()
`);
  await sl(1200);
  await p.screenshot({ path: '/tmp/keyreach.png' }).catch(() => {});
  await b.close().catch(() => {}); process.exit(0);
})().catch((e) => { console.log('DRIVER ' + String(e).slice(0, 200)); process.exit(0); });
