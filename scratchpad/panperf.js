// Interactive performance during a REAL middle-drag pan (the interaction the control
// harness proves moves the camera), at 60 Hz cadence. Reports frames actually rendered,
// per-frame busy time and draws per frame. Camera movement is asserted per model, using
// the same getCamera() string comparison the control uses.
const puppeteer = require('puppeteer-core');
const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const sl = (ms) => new Promise((r) => setTimeout(r, ms));
const run = (p, c) => p.evaluate((c) => { const m = window.fcInstance;
  const n = new TextEncoder().encode(c).length + 1; const q = m._malloc(n); m.stringToUTF8(c, q, n);
  (window.fcRunPy || ((mm, pp) => { mm._fcweb_run_python(pp); mm._free(pp); }))(m, q); }, c);
const pw = async (p, mk, ms) => { const t0 = Date.now();
  while (Date.now() - t0 < ms) { try { if (await p.evaluate((k) =>
    document.getElementById('log').textContent.includes(k), mk)) return true; } catch (e) {} await sl(400); } return false; };
let seq = 0;
const cam = async (p) => { const tag = 'CM' + (++seq);
  await run(p, ['import FreeCADGui as Gui,sys', 'c=Gui.activeDocument().activeView().getCamera()',
    "q=[l.strip() for l in c.splitlines() if 'position' in l or 'orientation' in l]",
    "sys.__stderr__.write('" + tag + " %s\\n'%(' ; '.join(q[:2])))"].join('\n'));
  await pw(p, tag, 20000);
  const log = await p.evaluate(() => document.getElementById('log').textContent);
  return ((log.match(new RegExp(tag + '[^\\n]*')) || [''])[0]).replace(tag + ' ', ''); };

const MODELS = process.argv.slice(2);
(async () => {
  const b = await puppeteer.launch({ executablePath: CHROME, headless: false, defaultViewport: null,
    args: ['--no-sandbox', '--use-gl=angle', '--use-angle=metal', '--window-size=1400,900'],
    protocolTimeout: 2400000, userDataDir: '/tmp/fc-panperf' });
  const p = (await b.pages())[0];
  await p.goto('http://localhost:8792/index.html', { waitUntil: 'domcontentloaded', timeout: 300000 });
  const t0 = Date.now();
  while (Date.now() - t0 < 300000) { if (await p.evaluate(() => !!(window.fcInstance && window.fcInstance._malloc))) break; await sl(1000); }
  await sl(9000);
  await p.evaluate(() => {
    window.__fr = [];
    const P = WebGL2RenderingContext.prototype, clear = P.clear;
    P.clear = function (m) { if (m & this.COLOR_BUFFER_BIT) window.__fr.push({ t: performance.now(), end: 0, d: 0 });
      return clear.apply(this, arguments); };
    ['drawArrays', 'drawElements'].forEach((nm) => { const o = P[nm];
      P[nm] = function () { const r = o.apply(this, arguments);
        const f = window.__fr[window.__fr.length - 1]; if (f) { f.end = performance.now(); f.d++; } return r; }; });
  });
  const c = await p.evaluate(() => { const h = document.getElementById('qt-shadow-container');
    const cv = h && h.shadowRoot && h.shadowRoot.querySelector('canvas');
    const r = (cv || document.body).getBoundingClientRect();
    return { x: Math.round(r.x + r.width * 0.55), y: Math.round(r.y + r.height * 0.5) }; });

  for (const M of MODELS) {
    await run(p, ['import sys, FreeCAD as App, FreeCADGui as Gui',
      'd=App.openDocument("/freecad/share/examples/' + M + '.FCStd")', 'Gui.updateGui()',
      'av=Gui.ActiveDocument.ActiveView', 'av.viewAxonometric(); av.fitAll(); Gui.updateGui()',
      'sys.__stderr__.write("OPEN ' + M + '\\n")'].join('\n'));
    if (!await pw(p, 'OPEN ' + M, 900000)) { console.log(M + ' open timed out'); continue; }
    await sl(2500);
    const a = await cam(p);
    await p.evaluate(() => { window.__fr = []; });
    await p.mouse.move(c.x, c.y);
    await p.mouse.down({ button: 'middle' });
    const t1 = Date.now();
    for (let i = 1; i <= 60; i++) { await p.mouse.move(c.x + Math.round(90 * Math.sin(i / 8)), c.y + Math.round(60 * Math.cos(i / 7))); await sl(16); }
    const wall = Date.now() - t1;
    await p.mouse.up({ button: 'middle' });
    await sl(900);
    const z = await cam(p);
    const st = await p.evaluate(() => {
      const f = window.__fr.filter((x) => x.d > 0 && x.end > x.t);
      const q = (arr, k) => (arr.length ? +arr.sort((m, n) => m - n)[Math.min(arr.length - 1, Math.floor(arr.length * k))].toFixed(1) : 0);
      return { frames: f.length, busyMed: q(f.map((x) => x.end - x.t), 0.5), busyP95: q(f.map((x) => x.end - x.t), 0.95),
               draws: q(f.map((x) => x.d), 0.5) };
    });
    console.log(M.padEnd(18) + 'moved=' + String(a !== z).padEnd(6) +
      ' frames=' + String(st.frames).padStart(3) + '/' + Math.round(wall / 16) +
      '  fps=' + String(+(st.frames / (wall / 1000)).toFixed(1)).padStart(5) +
      '  busy med=' + String(st.busyMed).padStart(6) + 'ms p95=' + String(st.busyP95).padStart(6) +
      'ms  draws/frame=' + st.draws);
    await run(p, 'App.closeDocument(App.ActiveDocument.Name)');
    await sl(2000);
  }
  await b.close().catch(() => {}); process.exit(0);
})().catch((e) => { console.log('DRIVER ' + e); process.exit(1); });
