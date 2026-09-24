// CAD navigation's rotate is a chord: hold the middle button, then press left (or right)
// and drag (Gui/Navigation/CADNavigationStyle.cpp:52, "Press middle+left or middle+right").
// A user reported (2026-09-24) that the chord does nothing on production. This drives the
// chord (middle then left, middle then right) and a middle-drag (pan) with real browser input, per
// gesture: the DOM pointer events the browser produced, the mouse events Qt delivered to the
// 3D view, and whether the camera actually moved. Exit 0 only if both chords rotate and the
// middle-drag pans without rotating. Fixed in Qt: patches/qt-wasm-chorded-mouse-buttons.patch.
// (A page-side re-dispatch of the chord as a synthetic pointerdown was tried first and did not
// reach Qt's windows; the Qt mapping is where the button is lost, so that is where it is fixed.)
//
//   node scratchpad/navchord.js [url]     (default: production)
const puppeteer = require('puppeteer-core');
const sl = (ms) => new Promise((r) => setTimeout(r, ms));
const URL = process.argv[2] || 'https://freecad.virtastic.app/';
const CHROME = process.env.CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe';

const run = (p, c) => p.evaluate((c) => { const m = window.fcInstance;
  const n = new TextEncoder().encode(c).length + 1; const q = m._malloc(n); m.stringToUTF8(c, q, n);
  window.fcRunPy(m, q); }, c);
let tag = 0;
async function ask(p, py, ms = 30000) {
  const m = 'Q' + (++tag) + 'Z';
  const t0 = Date.now(); let sent = 0;
  while (Date.now() - t0 < ms) {
    if (Date.now() - sent > 5000) { await run(p, py.replace(/@@/g, m)); sent = Date.now(); }
    const hit = (await p.evaluate(() => document.getElementById('log').textContent)).match(new RegExp(m + ' ([^\\n]*)'));
    if (hit) return hit[1];
    await sl(400);
  }
  return null;
}
const HEAD = 'import sys, json\nfrom PySide6 import QtWidgets, QtCore\nimport FreeCAD as App, FreeCADGui as Gui\n' +
  'def say(o):\n    sys.__stderr__.write("@@ " + json.dumps(o) + "\\n"); sys.__stderr__.flush()\n';
// a box, the view fitted, and an app-wide filter that records mouse events reaching the 3D view
const SETUP = HEAD +
  'd = App.newDocument("Nav"); d.addObject("Part::Box", "B"); d.recompute()\n' +
  'v = Gui.ActiveDocument.ActiveView; v.viewIsometric(); v.fitAll()\n' +
  'import builtins\n' +
  'class F(QtCore.QObject):\n' +
  '    def eventFilter(self, o, e):\n' +
  '        t = e.type()\n' +
  '        if t in (QtCore.QEvent.MouseButtonPress, QtCore.QEvent.MouseButtonRelease) and o.metaObject().className().startswith("QtGLWidget") or (t in (QtCore.QEvent.MouseButtonPress, QtCore.QEvent.MouseButtonRelease) and "View3D" in o.metaObject().className()) or (t in (QtCore.QEvent.MouseButtonPress, QtCore.QEvent.MouseButtonRelease) and o.objectName() == "QtGLWidget"):\n' +
  '            builtins._navlog.append([o.metaObject().className(), "press" if t == QtCore.QEvent.MouseButtonPress else "release", int(e.button().value), int(e.buttons().value)])\n' +
  '        elif t in (QtCore.QEvent.MouseButtonPress, QtCore.QEvent.MouseButtonRelease):\n' +
  '            builtins._navall.append([o.metaObject().className(), o.objectName(), "press" if t == QtCore.QEvent.MouseButtonPress else "release", int(e.button().value), int(e.buttons().value)])\n' +
  '        return False\n' +
  'builtins._navlog = []; builtins._navall = []; builtins._navf = F(); QtWidgets.QApplication.instance().installEventFilter(builtins._navf)\n' +
  'vw = Gui.getMainWindow().findChild(QtWidgets.QWidget, "View3DInventor") or v.graphicsView()\n' +
  'gv = v.graphicsView()\n' +
  'g = gv.viewport().mapToGlobal(gv.viewport().rect().center())\n' +
  'say({"nav": v.getNavigationType(), "center": [g.x(), g.y()], "vpclass": gv.viewport().metaObject().className()})\n';
const CAM = HEAD + 'import builtins, traceback\n' +
  'try:\n' +
  '    v = Gui.ActiveDocument.ActiveView\n' +
  '    q = v.getCameraOrientation().Q\n' +
  '    pos = [l.strip() for l in v.getCamera().splitlines() if l.strip().startswith("position")]\n' +
  '    say({"rot": [round(x, 4) for x in q], "pos": pos, "qt": builtins._navlog[-12:], "other": [x for x in builtins._navall if x[0] in ("QWidgetWindow", "QOpenGLWidget")][-12:]})\n' +
  '    builtins._navlog.clear(); builtins._navall.clear()\n' +
  'except Exception:\n' +
  '    say({"err": traceback.format_exc()[-400:]})\n';

(async () => {
  const b = await puppeteer.launch({ executablePath: CHROME, headless: false, defaultViewport: null,
    args: ['--no-sandbox', '--window-size=1400,950'], protocolTimeout: 900000,
    userDataDir: 'C:/Users/MICHAE~1/AppData/Local/Temp/fc-navchord-' + Date.now() });
  const p = (await b.pages())[0];
  await p.goto(URL, { waitUntil: 'domcontentloaded', timeout: 300000 });
  const t0 = Date.now();
  while (Date.now() - t0 < 420000) {
    if (await p.evaluate(() => !!window.__fcWorkReady && !!document.querySelector('#load.hide'))) break;
    await sl(2000);
  }
  await sl(12000);
  await p.keyboard.press('Escape'); await sl(500);
  const s = JSON.parse(await ask(p, SETUP, 60000) || 'null');
  console.log('setup: ' + JSON.stringify(s));
  await sl(3000);
  // DOM-side log: what the browser hands the page
  await p.evaluate(() => {
    window.__navdom = [];
    for (const t of ['pointerdown', 'pointermove', 'pointerup', 'mousedown', 'mouseup', 'auxclick', 'contextmenu'])
      window.addEventListener(t, (e) => { if (t === 'pointermove' && e.button === -1) return;
        window.__navdom.push([t, e.button, e.buttons, e.target && (e.target.id || e.target.className || e.target.tagName)].join(' ')); }, true);
  });
  const [cx, cy] = s.center;
  const gesture = async (name, fn) => {
    await p.evaluate(() => { window.__navdom = []; });
    const before = JSON.parse(await ask(p, CAM) || 'null');
    await p.mouse.move(cx, cy); await sl(300);
    await fn(); await sl(1500);
    const after = JSON.parse(await ask(p, CAM) || 'null');
    const dom = await p.evaluate(() => window.__navdom.slice(0, 14));
    if (!before || !after || before.err || after.err) { console.log('CAM failed: ' + JSON.stringify([before, after])); return {}; }
    const rotMoved = JSON.stringify(before.rot) !== JSON.stringify(after.rot);
    const posMoved = JSON.stringify(before.pos) !== JSON.stringify(after.pos);
    console.log('\n== ' + name + ': camera rotation ' + (rotMoved ? 'CHANGED' : 'unchanged') + ', position ' + (posMoved ? 'CHANGED' : 'unchanged'));
    console.log('   DOM: ' + JSON.stringify(dom));
    console.log('   Qt 3D view: ' + JSON.stringify(after.qt));
    console.log('   Qt other widgets: ' + JSON.stringify(after.other));
    return { rotMoved, posMoved };
  };
  const drag = async (steps) => { for (let i = 1; i <= steps; i++) { await p.mouse.move(cx + i * 8, cy + i * 3); await sl(30); } };
  const r1 = await gesture('middle held, then left, drag (CAD rotate)', async () => {
    await p.mouse.down({ button: 'middle' }); await sl(150);
    await p.mouse.down({ button: 'left' }); await sl(150);
    await drag(20);
    await p.mouse.up({ button: 'left' }); await p.mouse.up({ button: 'middle' });
  });
  const r2 = await gesture('middle held, then right, drag (CAD rotate)', async () => {
    await p.mouse.down({ button: 'middle' }); await sl(150);
    await p.mouse.down({ button: 'right' }); await sl(150);
    await drag(20);
    await p.mouse.up({ button: 'right' }); await p.mouse.up({ button: 'middle' });
  });
  const r3 = await gesture('middle drag (CAD pan)', async () => {
    await p.mouse.down({ button: 'middle' }); await sl(150);
    await drag(20);
    await p.mouse.up({ button: 'middle' });
  });
  const pass = r1.rotMoved && r2.rotMoved && r3.posMoved && !r3.rotMoved;
  console.log('\n' + (pass ? 'ALL PASS' : 'FAIL') + ': middle+left rotates ' + !!r1.rotMoved + ', middle+right rotates ' + !!r2.rotMoved + ', middle pans without rotating ' + !!(r3.posMoved && !r3.rotMoved));
  await p.screenshot({ path: process.env.SHOT || 'C:/Users/MICHAE~1/AppData/Local/Temp/navchord.png' });
  await b.close();
  process.exit(pass ? 0 : 1);
})().catch((e) => { console.error(e); process.exit(2); });
