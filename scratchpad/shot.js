// Screenshot a model at a fixed camera + report draws/frame and pan fps. Used as the
// correctness gate for the line-batching change: the image must be pixel-identical.
const puppeteer = require('puppeteer-core');
const fs = require('fs');
const CHROME = process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';  // set CHROME_PATH to run off macOS
const sl = (ms) => new Promise((r) => setTimeout(r, ms));
const run = (p, c) => p.evaluate((c) => { const m = window.fcInstance;
  const n = new TextEncoder().encode(c).length + 1; const q = m._malloc(n); m.stringToUTF8(c, q, n);
  (window.fcRunPy || ((mm, pp) => { mm._fcweb_run_python(pp); mm._free(pp); }))(m, q); }, c);
const pw = async (p, mk, ms) => { const t0 = Date.now();
  while (Date.now() - t0 < ms) { try { if (await p.evaluate((k) =>
    document.getElementById('log').textContent.includes(k), mk)) return true; } catch (e) {} await sl(400); } return false; };
const MODEL = process.argv[2], OUT = process.argv[3], QS = process.argv[4] || '';
(async () => {
  const b = await puppeteer.launch({ executablePath: CHROME, headless: false, defaultViewport: null,
    args: ['--no-sandbox', '--use-gl=angle', '--use-angle=metal', '--window-size=1400,900'],
    protocolTimeout: 2400000, userDataDir: '/tmp/fc-shot' });
  const p = (await b.pages())[0];
  await p.goto('http://localhost:8792/index.html' + QS, { waitUntil: 'domcontentloaded', timeout: 300000 });
  const t0 = Date.now();
  while (Date.now() - t0 < 300000) { if (await p.evaluate(() => !!(window.fcInstance && window.fcInstance._malloc))) break; await sl(1000); }
  await sl(10000);
  await p.evaluate(() => { window.__n = 0; window.__f = 0;
    const P = WebGL2RenderingContext.prototype, da = P.drawArrays, cl = P.clear;
    P.drawArrays = function () { window.__n++; return da.apply(this, arguments); };
    P.clear = function (m) { if (m & this.COLOR_BUFFER_BIT) window.__f++; return cl.apply(this, arguments); }; });
  await run(p, ['import sys, FreeCAD as App, FreeCADGui as Gui',
    'd=App.openDocument("/freecad/share/examples/' + MODEL + '.FCStd")', 'Gui.updateGui()',
    'av=Gui.ActiveDocument.ActiveView', 'av.viewAxonometric(); av.fitAll(); Gui.updateGui()',
    'sys.__stderr__.write("OPEN\\n")'].join('\n'));
  await pw(p, 'OPEN', 900000); await sl(4000);
  // deterministic camera so two runs are comparable
  await run(p, 'import FreeCADGui as Gui\nGui.ActiveDocument.ActiveView.viewAxonometric()\n' +
    'Gui.SendMsgToActiveView("ViewFit")\nGui.updateGui()');
  await sl(3000);
  await p.evaluate(() => { window.__n = 0; window.__f = 0; });
  const c = await p.evaluate(() => { const h = document.getElementById('qt-shadow-container');
    const cv = h && h.shadowRoot && h.shadowRoot.querySelector('canvas');
    const r = (cv || document.body).getBoundingClientRect();
    return { x: r.x + r.width * 0.55, y: r.y + r.height * 0.5 }; });
  await p.mouse.move(c.x, c.y); await p.mouse.down({ button: 'middle' });
  const t1 = Date.now();
  for (let i = 1; i <= 40; i++) { await p.mouse.move(c.x + Math.round(70 * Math.sin(i / 7)), c.y + Math.round(45 * Math.cos(i / 6))); await sl(16); }
  const wall = Date.now() - t1;
  await p.mouse.up({ button: 'middle' }); await sl(1200);
  const st = await p.evaluate(() => ({ n: window.__n, f: window.__f, lb: window.__glSkipped || null }));
  // return to the exact same camera before shooting
  await run(p, 'import FreeCADGui as Gui\nGui.ActiveDocument.ActiveView.viewAxonometric()\n' +
    'Gui.SendMsgToActiveView("ViewFit")\nGui.updateGui()');
  await sl(3500);
  await p.screenshot({ path: OUT });
  console.log(MODEL + '  draws/frame=' + Math.round(st.n / Math.max(1, st.f)) +
    '  fps=' + (st.f / (wall / 1000)).toFixed(1) +
    (st.lb ? '\n  skipped/frame=' + JSON.stringify(st.lb && Object.fromEntries(Object.entries(st.lb).map(([k,v])=>[k,Math.round(v/Math.max(1,st.f))]))) : '') + '  -> ' + OUT);
  await b.close().catch(() => {}); process.exit(0);
})().catch((e) => { console.log('DRIVER ' + String(e).slice(0, 200)); process.exit(1); });
