// Bitmap import (user report 2026-10-09): an Image::ImagePlane shows in the tree but not the 3D view.
// Builds a 64x64 red/blue PNG with QImage, adds the plane the way Gui/FileHandler.cpp openImage() does,
// then screenshots the viewport and samples its centre pixel.
//   node scratchpad/imageplane.js [url]
const puppeteer = require('puppeteer-core');
const sl = (ms) => new Promise((r) => setTimeout(r, ms));
const NL = String.fromCharCode(10);
const URL = process.argv[2] || 'https://freecad.virtastic.app/';
const runPy = (p, c) => p.evaluate((c) => { const m = window.fcInstance; const n = new TextEncoder().encode(c).length + 1; const q = m._malloc(n); m.stringToUTF8(c, q, n); window.fcRunPy(m, q); }, c);
(async () => {
  const b = await puppeteer.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: false, args: ['--no-sandbox', '--use-gl=angle', '--enable-features=SharedArrayBuffer', '--window-size=1400,900'], defaultViewport: { width: 1400, height: 900 }, protocolTimeout: 900000, userDataDir: 'C:/Users/MICHAE~1/AppData/Local/Temp/fc-ip-' + Date.now() });
  const p = (await b.pages())[0];
  p.on('console', async (m) => { const t = m.text(); if (/imgplane|error|rejected|abort|TODO|glGet|null function|unreachable/i.test(t)) { let st = ''; try { const a = m.args(); if (a[1]) st = await a[1].evaluate((e) => e && e.stack); } catch (e) {} console.log('  [page] ' + t.slice(0, 200) + (st ? NL + String(st).slice(0, 1500) : '')); } });
  p.on('pageerror', (e) => console.log('  [pageerror] ' + String(e.stack || e.message || e).slice(0, 1800)));
  await p.evaluateOnNewDocument(() => { window.addEventListener('unhandledrejection', (ev) => { const r = ev.reason; console.log('imgplane UNHANDLED ' + (r && (r.stack || r.message) || r)); }); });
  await p.goto(URL, { waitUntil: 'domcontentloaded', timeout: 300000 });
  const t = Date.now();
  while (Date.now() - t < 420000) { if (await p.evaluate(() => !!window.__fcWorkReady && !!(window.fcInstance && window.fcInstance._malloc))) break; await sl(1500); }
  await sl(8000);
  await runPy(p, ['import FreeCAD as App, FreeCADGui as Gui, sys',
    'from PySide import QtGui',
    'img = QtGui.QImage(64, 64, QtGui.QImage.Format_RGB32)',
    'img.fill(QtGui.QColor(220, 30, 30))',
    'print("imgplane save", img.save("/tmp/t.png"))',
    'd = App.newDocument("IP")',
    ...(process.env.NOPLANE ? ['o = d.addObject("Part::Box", "t")'] : ['o = d.addObject("Image::ImagePlane", "t")']),
    ...(process.env.NOPLANE ? [] : ['o.ImageFile = "/tmp/t.png"']),
    'bx = d.addObject("Part::Box", "Box"); bx.Placement.Base = App.Vector(80, 0, 0)',
    'print("imgplane created")',
    'd.recompute()',
    'print("imgplane recomputed")'].join(NL));
  await sl(4000);
  await runPy(p, ['import FreeCADGui as Gui', 'print("imgplane before view")', 'v = Gui.ActiveDocument.ActiveView', 'print("imgplane view", v)', 'v.viewTop()', 'print("imgplane viewTop")', 'v.fitAll()', 'print("imgplane fitAll")', 'Gui.updateGui()', 'print("imgplane updated")'].join(NL));
  await sl(6000);
  await p.screenshot({ path: 'C:/tmp/imageplane' + (process.env.NOPLANE ? '-ctl' : '') + '.png' });
  console.log('shot C:/tmp/imageplane' + (process.env.NOPLANE ? '-ctl' : '') + '.png');
  await b.close();
})();
