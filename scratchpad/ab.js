// A/B the redundant-state elimination in ONE browser session, alternating and repeating,
// because single runs drift by 3x. Each trial: reload with/without ?noredundant=1, open
// the model, fix the camera, pan, report frames per second of wall clock.
const puppeteer = require('puppeteer-core');
const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const sl = (ms) => new Promise((r) => setTimeout(r, ms));
const run = (p, c) => p.evaluate((c) => { const m = window.fcInstance;
  const n = new TextEncoder().encode(c).length + 1; const q = m._malloc(n); m.stringToUTF8(c, q, n);
  (window.fcRunPy || ((mm, pp) => { mm._fcweb_run_python(pp); mm._free(pp); }))(m, q); }, c);
const pw = async (p, mk, ms) => { const t0 = Date.now();
  while (Date.now() - t0 < ms) { try { if (await p.evaluate((k) =>
    document.getElementById('log').textContent.includes(k), mk)) return true; } catch (e) {} await sl(400); } return false; };
const MODEL = process.argv[2] || 'BIMExample';
const TRIALS = +(process.argv[3] || 3);

async function trial(p, off) {
  await p.goto('http://localhost:8791/index.html' + (off ? '?noredundant=1' : ''),
    { waitUntil: 'domcontentloaded', timeout: 300000 });
  const t0 = Date.now();
  while (Date.now() - t0 < 300000) { if (await p.evaluate(() => !!(window.fcInstance && window.fcInstance._malloc))) break; await sl(1000); }
  await sl(9000);
  await p.evaluate(() => { window.__n = 0; window.__f = 0;
    const P = WebGL2RenderingContext.prototype, da = P.drawArrays, cl = P.clear;
    P.drawArrays = function () { window.__n++; return da.apply(this, arguments); };
    P.clear = function (m) { if (m & this.COLOR_BUFFER_BIT) window.__f++; return cl.apply(this, arguments); }; });
  await run(p, ['import sys, FreeCAD as App, FreeCADGui as Gui',
    'd=App.openDocument("/freecad/share/examples/' + MODEL + '.FCStd")', 'Gui.updateGui()',
    'av=Gui.ActiveDocument.ActiveView', 'av.viewAxonometric(); av.fitAll(); Gui.updateGui()',
    'sys.__stderr__.write("OPEN\\n")'].join('\n'));
  await pw(p, 'OPEN', 900000); await sl(3500);
  await run(p, 'import FreeCADGui as Gui\nGui.ActiveDocument.ActiveView.viewAxonometric()\nGui.SendMsgToActiveView("ViewFit")\nGui.updateGui()');
  await sl(2500);
  const c = await p.evaluate(() => { const h = document.getElementById('qt-shadow-container');
    const cv = h && h.shadowRoot && h.shadowRoot.querySelector('canvas');
    const r = (cv || document.body).getBoundingClientRect();
    return { x: r.x + r.width * 0.55, y: r.y + r.height * 0.5 }; });
  await p.evaluate(() => { window.__n = 0; window.__f = 0; });
  await p.mouse.move(c.x, c.y); await p.mouse.down({ button: 'middle' });
  const t1 = Date.now();
  for (let i = 1; i <= 40; i++) { await p.mouse.move(c.x + Math.round(70 * Math.sin(i / 7)), c.y + Math.round(45 * Math.cos(i / 6))); await sl(16); }
  const wall = Date.now() - t1;
  await p.mouse.up({ button: 'middle' }); await sl(700);
  const st = await p.evaluate(() => ({ n: window.__n, f: window.__f, sk: window.__glSkipped || null }));
  return { fps: +(st.f / (wall / 1000)).toFixed(2), draws: Math.round(st.n / Math.max(1, st.f)), skipped: !!st.sk };
}
(async () => {
  const b = await puppeteer.launch({ executablePath: CHROME, headless: false, defaultViewport: null,
    args: ['--no-sandbox', '--use-gl=angle', '--use-angle=metal', '--window-size=1400,900'],
    protocolTimeout: 2400000, userDataDir: '/tmp/fc-ab' });
  const p = (await b.pages())[0];
  const on = [], off = [];
  for (let i = 0; i < TRIALS; i++) {
    off.push(await trial(p, true));
    on.push(await trial(p, false));
  }
  const med = (a) => a.map((x) => x.fps).sort((x, y) => x - y)[a.length >> 1];
  console.log('OFF (baseline) fps: ' + off.map((x) => x.fps).join(', ') + '   median ' + med(off));
  console.log('ON  (skipping) fps: ' + on.map((x) => x.fps).join(', ') + '   median ' + med(on));
  console.log('draws/frame off=' + off[0].draws + ' on=' + on[0].draws +
    '   change: ' + (((med(on) / med(off)) - 1) * 100).toFixed(1) + '%');
  await b.close().catch(() => {}); process.exit(0);
})().catch((e) => { console.log('DRIVER ' + String(e).slice(0, 200)); process.exit(1); });
