// Does Coin's render culling help the heavy scene? Same real middle-drag pan, measured
// with culling OFF then ON, on the same loaded document so nothing else differs.
const puppeteer = require('puppeteer-core');
const CHROME = process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';  // set CHROME_PATH to run off macOS
const sl = (ms) => new Promise((r) => setTimeout(r, ms));
const run = (p, c) => p.evaluate((c) => { const m = window.fcInstance;
  const n = new TextEncoder().encode(c).length + 1; const q = m._malloc(n); m.stringToUTF8(c, q, n);
  (window.fcRunPy || ((mm, pp) => { mm._fcweb_run_python(pp); mm._free(pp); }))(m, q); }, c);
const pw = async (p, mk, ms) => { const t0 = Date.now();
  while (Date.now() - t0 < ms) { try { if (await p.evaluate((k) =>
    document.getElementById('log').textContent.includes(k), mk)) return true; } catch (e) {} await sl(400); } return false; };
const MODEL = process.argv[2] || 'BIMExample';
(async () => {
  const b = await puppeteer.launch({ executablePath: CHROME, headless: false, defaultViewport: null,
    args: ['--no-sandbox', '--use-gl=angle', '--use-angle=metal', '--window-size=1400,900'],
    protocolTimeout: 2400000, userDataDir: '/tmp/fc-cullperf' });
  const p = (await b.pages())[0];
  await p.goto('http://localhost:8791/index.html', { waitUntil: 'domcontentloaded', timeout: 300000 });
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
        const f = window.__fr[window.__fr.length - 1]; if (f) { f.end = performance.now(); f.d++; }
        window.__draws = (window.__draws || 0) + 1; return r; }; });
  });
  await run(p, ['import sys, FreeCAD as App, FreeCADGui as Gui',
    'd=App.openDocument("/freecad/share/examples/' + MODEL + '.FCStd")', 'Gui.updateGui()',
    'av=Gui.ActiveDocument.ActiveView', 'av.viewAxonometric(); av.fitAll(); Gui.updateGui()',
    'sys.__stderr__.write("OPEN\\n")'].join('\n'));
  await pw(p, 'OPEN', 900000); await sl(2500);
  const c = await p.evaluate(() => { const h = document.getElementById('qt-shadow-container');
    const cv = h && h.shadowRoot && h.shadowRoot.querySelector('canvas');
    const r = (cv || document.body).getBoundingClientRect();
    return { x: Math.round(r.x + r.width * 0.55), y: Math.round(r.y + r.height * 0.5) }; });

  const measure = async (label) => {
    await p.evaluate(() => { window.__fr = []; window.__draws = 0; });
    await p.mouse.move(c.x, c.y); await p.mouse.down({ button: 'middle' });
    const t1 = Date.now();
    for (let i = 1; i <= 50; i++) { await p.mouse.move(c.x + Math.round(90 * Math.sin(i / 8)), c.y + Math.round(60 * Math.cos(i / 7))); await sl(16); }
    const wall = Date.now() - t1;
    await p.mouse.up({ button: 'middle' }); await sl(900);
    const st = await p.evaluate(() => {
      const f = window.__fr.filter((x) => x.d > 0);
      const busy = f.map((x) => x.end - x.t).sort((m, n) => m - n);
      return { frames: f.length, draws: window.__draws,
        p95: busy.length ? +busy[Math.floor(busy.length * 0.95)].toFixed(1) : 0 };
    });
    console.log(label.padEnd(22) + 'fps=' + String(+(st.frames / (wall / 1000)).toFixed(1)).padStart(5) +
      '  frames=' + String(st.frames).padStart(4) + '  totalDraws=' + String(st.draws).padStart(7) +
      '  drawsPerFrame=' + String(Math.round(st.draws / Math.max(1, st.frames))).padStart(5) +
      '  p95=' + st.p95 + 'ms');
  };
  await measure('culling OFF (default)');
  await run(p, ['import FreeCADGui as Gui, sys',
    'sg = Gui.ActiveDocument.ActiveView.getSceneGraph()',
    'sg.renderCulling = "ON"',
    'Gui.updateGui()',
    'sys.__stderr__.write("CULLON %s\\n" % sg.renderCulling.get())'].join('\n'));
  await sl(1500);
  const log = await p.evaluate(() => document.getElementById('log').textContent);
  console.log('renderCulling now: ' + ((log.match(/CULLON [^\n]*/g) || ['(failed)']).pop()));
  await measure('culling ON');
  await b.close().catch(() => {}); process.exit(0);
})().catch((e) => { console.log('DRIVER ' + e); process.exit(1); });
