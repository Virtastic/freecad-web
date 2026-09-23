// Is a preselected face highlighted evenly? (GitHub issue #1: a hovered face showed a
// blocky mottle of highlight and base colour, the signature of two passes whose depths
// disagree.) Opens the Assembly example, moves the REAL mouse over the bucket until
// FreeCAD preselects a face, and measures how much of that face took the highlight.
//   node scratchpad/hilite.js [url]
const puppeteer = require('puppeteer-core');
const zlib = require('zlib'), fs = require('fs');
const sl = (ms) => new Promise((r) => setTimeout(r, ms));
const NL = String.fromCharCode(10);
const URL = process.argv[2] || 'http://127.0.0.1:8792/freecad-gui.html';
const runPy = (p, c) => p.evaluate((c) => { const m = window.fcInstance; const n = new TextEncoder().encode(c).length + 1; const q = m._malloc(n); m.stringToUTF8(c, q, n); window.fcRunPy(m, q); }, c);
const readFile = (p, f) => p.evaluate((f) => { try { return window.fcInstance.FS.readFile(f, { encoding: 'utf8' }); } catch (e) { return null; } }, f);
(async () => {
  const b = await puppeteer.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: true,
    defaultViewport: { width: 1400, height: 900 }, args: ['--no-sandbox', '--use-gl=angle'], protocolTimeout: 900000,
    userDataDir: 'C:/Users/MICHAE~1/AppData/Local/Temp/fc-hl-' + Date.now() });
  const p = (await b.pages())[0];
  const shaderErr = [];
  p.on('console', (m) => { const t = m.text(); if (/shader|glsl|compile|link.*program/i.test(t) && /err|fail/i.test(t)) shaderErr.push(t.slice(0, 200)); });
  await p.goto(URL, { waitUntil: 'domcontentloaded', timeout: 300000 });
  const t = Date.now();
  while (Date.now() - t < 420000) { if (await p.evaluate(() => !!window.__fcWorkReady && !!(window.fcInstance && window.fcInstance._malloc) && document.querySelector('#load.hide,#load[hidden]') !== undefined)) break; await sl(1500); }
  await sl(9000);
  // the reporter's scene: the Assembly example, zoomed onto the bucket (its parts are
  // App::Link objects, which the plain-box case does not exercise)
  await runPy(p, ['import FreeCAD as App, FreeCADGui as Gui, glob',
    'f=[x for x in glob.glob("/freecad/share/examples/*ssembly*") ][0]',
    'd=App.openDocument(f)', 'Gui.Selection.clearSelection()',
    'Gui.Selection.addSelection(d.Name, "Assembly", "Bucket001.")',
    'v=Gui.ActiveDocument.ActiveView', 'v.viewIsometric(); Gui.SendMsgToActiveView("ViewSelection"); Gui.Selection.clearSelection(); Gui.updateGui()',
    'open("/tmp/hl.txt","w").write(f)'].join(NL));
  await sl(12000);
  console.log('  opened: ' + await readFile(p, '/tmp/hl.txt'));
  await sl(6000);
  const out = [];
  for (const [x, y] of [[545, 400], [555, 410], [560, 420]]) {
    await p.mouse.move(x - 40, y - 30); await sl(300);
    await p.mouse.move(x, y, { steps: 8 }); await sl(2500);
    await runPy(p, 'import FreeCADGui as Gui' + NL + 'open("/tmp/pre.txt","w").write(str(Gui.Selection.getPreselection().SubElementNames))');
    await sl(1500);
    out.push(await readFile(p, '/tmp/pre.txt'));
  }
  console.log('  preselected: ' + JSON.stringify(out));
  console.log('  shader errors: ' + shaderErr.length + (shaderErr.length ? ' ' + JSON.stringify(shaderErr.slice(0, 3)) : ''));
  await p.screenshot({ path: 'C:/tmp/hilite.png' });
  await b.close();
})();
