// Quick measure in the status bar (kwahoo2, Discord 2026-09-23): desktop FreeCAD 1.1.3 shows
// e.g. "Radius: 5.00 mm" at the right of the status bar when an edge or face is selected.
// Selects a cylinder's circular edge with a REAL click and reads that label back.
//   node scratchpad/quickmeasure.js [url]
const puppeteer = require('puppeteer-core');
const sl = (ms) => new Promise((r) => setTimeout(r, ms));
const NL = String.fromCharCode(10);
const URL = process.argv[2] || 'https://freecad.virtastic.app/';
const runPy = (p, c) => p.evaluate((c) => { const m = window.fcInstance; const n = new TextEncoder().encode(c).length + 1; const q = m._malloc(n); m.stringToUTF8(c, q, n); window.fcRunPy(m, q); }, c);
const ask = async (p, code) => {
  for (let i = 0; i < 6; i++) {
    await p.evaluate(() => { try { window.fcInstance.FS.unlink('/tmp/qm.json'); } catch (e) {} });
    await runPy(p, code); await sl(2500);
    const r = await p.evaluate(() => { try { return window.fcInstance.FS.readFile('/tmp/qm.json', { encoding: 'utf8' }); } catch (e) { return null; } });
    if (r) return JSON.parse(r);
  }
  return null;
};
const STATE = ['import FreeCADGui as Gui, json, sys', 'from PySide import QtWidgets',
  'mw = Gui.getMainWindow()', 'lab = mw.findChild(QtWidgets.QLabel, "rightSideLabel")',
  'import FreeCAD as App', 'g = App.ParamGet("User parameter:BaseApp/Preferences/MainWindow")',
  'open("/tmp/qm.json","w").write(json.dumps({"measureGui": "MeasureGui" in sys.modules, "label": lab.text() if lab else None, "labelVisible": bool(lab and lab.isVisible()), "statusBarVisible": mw.statusBar().isVisible(), "sel": [list(s.SubElementNames) for s in Gui.Selection.getSelectionEx()]}))'].join(NL);
(async () => {
  const b = await puppeteer.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: true, args: ['--no-sandbox', '--use-gl=angle'], defaultViewport: { width: 1400, height: 900 }, protocolTimeout: 900000, userDataDir: 'C:/Users/MICHAE~1/AppData/Local/Temp/fc-qm-' + Date.now() });
  const p = (await b.pages())[0];
  await p.goto(URL, { waitUntil: 'domcontentloaded', timeout: 300000 });
  const t = Date.now();
  while (Date.now() - t < 420000) { if (await p.evaluate(() => !!window.__fcWorkReady && !!(window.fcInstance && window.fcInstance._malloc))) break; await sl(1500); }
  await sl(8000);
  console.log('  at boot: ' + JSON.stringify(await ask(p, STATE)));
  await runPy(p, ['import FreeCAD as App, FreeCADGui as Gui', 'd = App.newDocument("Q")', 'c = d.addObject("Part::Cylinder", "C"); c.Radius = 5; c.Height = 20', 'd.recompute()',
    'v = Gui.ActiveDocument.ActiveView', 'v.viewTop(); v.fitAll(); Gui.updateGui()', ...(process.env.FORCE_SB ? ['Gui.getMainWindow().statusBar().show()'] : [])].join(NL));
  await sl(5000);
  // find a pixel on the cylinder's top circular edge from FreeCAD's own picking, then click it
  const pick = await ask(p, ['import FreeCADGui as Gui, json', 'v = Gui.ActiveDocument.ActiveView', 'w, h = v.getSize()', 'hit = None',
    'for x in range(0, w, 4):', '    info = v.getObjectInfo((x, h // 2))', '    if info and str(info.get("Component", "")).startswith("Edge"):',
    '        hit = [x, h // 2, info["Component"]]', '        break',
    'mw = Gui.getMainWindow()', 'from PySide import QtWidgets', 'gl = max([q for q in mw.findChildren(QtWidgets.QWidget) if q.metaObject().className() == "QOpenGLWidget"], key=lambda q: q.width() * q.height())',
    'o = gl.mapTo(mw, gl.rect().topLeft())', 'open("/tmp/qm.json","w").write(json.dumps({"hit": hit, "origin": [o.x(), o.y()], "size": [w, h]}))'].join(NL));
  console.log('  pick: ' + JSON.stringify(pick));
  if (pick && pick.hit) {
    // viewer y is from the bottom in getObjectInfo coordinates? getObjectInfo takes window coords (y down)
    // FreeCAD's window starts where #screen starts (the hosted site puts a 40 px bar above it).
    const off = await p.evaluate(() => { const r = document.getElementById('screen').getBoundingClientRect(); return [r.left, r.top]; });
    await p.mouse.click(off[0] + pick.origin[0] + pick.hit[0], off[1] + pick.origin[1] + pick.hit[1]); await sl(2500);
  }
  const s = await ask(p, STATE);
  console.log('  after clicking the edge: ' + JSON.stringify(s));
  await p.screenshot({ path: 'C:/tmp/quickmeasure.png' });
  await b.close();
})();
