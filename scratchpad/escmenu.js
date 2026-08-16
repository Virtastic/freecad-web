// Does Escape dismiss an open Qt menu, and if not, where is the key going?
//
// Recorded as a known limitation ("clicking away works"). Before accepting that, find out
// whether the keydown even reaches Qt: everything Qt draws lives inside a canvas in a
// SHADOW ROOT, so if focus sits on the document body the key never gets there.
//
// Usage: node scratchpad/escmenu.js [url]
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
    protocolTimeout: 1200000, userDataDir: '/tmp/fc-esc' });
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

  // where does the DOM think focus is, and is the Qt canvas focusable?
  const focus0 = await p.evaluate(() => {
    const d = (r) => r && r.activeElement
      ? (r.activeElement.tagName + (r.activeElement.id ? '#' + r.activeElement.id : '')
         + (r.activeElement.shadowRoot ? ' -> ' + d(r.activeElement.shadowRoot) : ''))
      : 'none';
    const cs = [...document.querySelectorAll('*')].filter((e) => e.shadowRoot);
    const canv = cs.flatMap((e) => [...e.shadowRoot.querySelectorAll('canvas')]);
    return { active: d(document), shadowHosts: cs.length, canvases: canv.length,
             canvasTabIndex: canv.length ? canv[0].getAttribute('tabindex') : null };
  });
  console.log('focus before: ' + JSON.stringify(focus0));

  // open the View menu by a real click on its menubar item
  await run(p, `
import sys
from PySide6 import QtWidgets
import FreeCADGui as Gui
mw = Gui.getMainWindow()
for a in mw.menuBar().actions():
    if a.menu() and "view" in (a.text() or "").lower().replace("&",""):
        r = mw.menuBar().actionGeometry(a)
        g = mw.menuBar().mapToGlobal(r.center())
        sys.__stderr__.write("MENU %d %d %s\\n" % (g.x(), g.y(), a.text()))
        break
sys.__stderr__.flush()
`);
  await sl(1800);
  const mm = /MENU (\d+) (\d+)/.exec(await last(p, /MENU [^\n]*/g));
  if (!mm) { console.log('menubar item not found'); await b.close(); process.exit(0); }
  await sl(4000);          // let the menubar finish laying out (slower over the network)
  await p.mouse.click(+mm[1], +mm[2]);
  await sl(3500);

  const popupState = async (tag) => {
    await run(p, `
import sys
from PySide6 import QtWidgets
w = QtWidgets.QApplication.activePopupWidget()
sys.__stderr__.write("POP ${tag} %s\\n" % ("open:" + w.__class__.__name__ if w else "none"))
sys.__stderr__.flush()
`);
    await sl(1500);
    return (await last(p, new RegExp('POP ' + tag + ' [^\\n]*', 'g'))).replace('POP ' + tag + ' ', '');
  };
  let opened = await popupState('A');
  if (opened === 'none') {           // retry once before drawing any conclusion
    await p.mouse.click(+mm[1], +mm[2]);
    await sl(3500);
    opened = await popupState('A2');
  }
  console.log('after clicking View: popup ' + opened);
  if (opened === 'none') {
    console.log('INCONCLUSIVE: the menu never opened, so this run says nothing about Escape');
    await b.close().catch(() => {}); process.exit(0);
  }
  const focus1 = await p.evaluate(() => {
    const d = (r) => r && r.activeElement
      ? (r.activeElement.tagName + (r.activeElement.id ? '#' + r.activeElement.id : '')
         + (r.activeElement.shadowRoot ? ' -> ' + d(r.activeElement.shadowRoot) : ''))
      : 'none';
    return d(document);
  });
  console.log('focus with menu open: ' + focus1);

  await p.keyboard.press('Escape');
  await sl(2500);
  console.log('after Escape:        popup ' + await popupState('B'));

  // control: does a click elsewhere close it? (the documented workaround)
  await p.mouse.click(700, 600);
  await sl(2000);
  console.log('after click-away:    popup ' + await popupState('C'));

  await b.close().catch(() => {}); process.exit(0);
})().catch((e) => { console.log('DRIVER ' + String(e).slice(0, 200)); process.exit(0); });
