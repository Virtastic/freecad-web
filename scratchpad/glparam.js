// Which GL parameters are queried per frame, and from where. getParameter is a
// synchronous round-trip to the GPU process; at thousands per frame it IS the frame time.
const puppeteer = require('puppeteer-core');
const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const sl = (ms) => new Promise((r) => setTimeout(r, ms));
const run = (p, c) => p.evaluate((c) => { const m = window.fcInstance;
  const n = new TextEncoder().encode(c).length + 1; const q = m._malloc(n); m.stringToUTF8(c, q, n);
  (window.fcRunPy || ((mm, pp) => { mm._fcweb_run_python(pp); mm._free(pp); }))(m, q); }, c);
const waitFor = async (p, mark, ms) => { const t0 = Date.now();
  while (Date.now() - t0 < ms) { const t = await p.evaluate(() => (document.getElementById('log') || {}).textContent || '');
    if (t.includes(mark)) return true; await sl(500); } return false; };
(async () => {
  const b = await puppeteer.launch({ executablePath: CHROME, headless: false, defaultViewport: null,
    args: ['--no-sandbox', '--use-gl=angle', '--use-angle=metal', '--window-size=1400,900'],
    protocolTimeout: 2400000, userDataDir: '/tmp/fc-glparam' });
  const p = (await b.pages())[0];
  await p.goto('http://localhost:8791/index.html', { waitUntil: 'domcontentloaded', timeout: 300000 });
  const t0 = Date.now();
  while (Date.now() - t0 < 300000) { if (await p.evaluate(() => !!(window.fcInstance && window.fcInstance._malloc))) break; await sl(1000); }
  await sl(9000);
  await run(p, ['import sys, FreeCAD as App, FreeCADGui as Gui',
    'd=App.openDocument("/freecad/share/examples/EngineBlock.FCStd")', 'Gui.updateGui()',
    'av=Gui.ActiveDocument.ActiveView', 'av.viewAxonometric(); av.fitAll(); Gui.updateGui()',
    'sys.__stderr__.write("VP-OPEN\\n"); sys.__stderr__.flush()'].join('\n'));
  await waitFor(p, 'VP-OPEN', 600000); await sl(3000);

  await p.evaluate(() => {
    window.__pn = {}; window.__stk = {}; window.__frames = 0;
    const P = WebGL2RenderingContext.prototype;
    const names = {};
    // reading some prototype props invokes a getter with the wrong receiver
    for (const k in P) { let v; try { v = P[k]; } catch (e) { continue; }
      if (typeof v === 'number') { (names[v] = names[v] || []).push(k); } }
    window.__names = names;
    const gp = P.getParameter;
    P.getParameter = function (pn) {
      window.__pn[pn] = (window.__pn[pn] || 0) + 1;
      const s = (new Error().stack || '').split('\n').slice(2, 4).join(' | ').replace(/https?:\/\/[^ )]+\//g, '');
      window.__stk[s] = (window.__stk[s] || 0) + 1;
      return gp.apply(this, arguments);
    };
    const clear = P.clear;
    P.clear = function (m) { if (m & this.COLOR_BUFFER_BIT) window.__frames++; return clear.apply(this, arguments); };
    // also time how long getParameter actually costs
    window.__gpTime = 0;
    const gp2 = P.getParameter;
    P.getParameter = function () { const a = performance.now(); const r = gp2.apply(this, arguments); window.__gpTime += performance.now() - a; return r; };
  });
  await p.evaluate(() => { window.__pn = {}; window.__stk = {}; window.__frames = 0; window.__gpTime = 0; });
  await p.mouse.move(700, 450); await p.mouse.down({ button: 'left' });
  const t1 = Date.now();
  for (let i = 0; i < 60; i++) { await p.mouse.move(700 + Math.round(150 * Math.sin(i / 7)), 450 + Math.round(100 * Math.cos(i / 6))); }
  await p.mouse.up({ button: 'left' });
  const wall = Date.now() - t1;
  const out = await p.evaluate(() => {
    const top = Object.entries(window.__pn).sort((a, b) => b[1] - a[1]).slice(0, 8)
      .map(([pn, n]) => [(window.__names[pn] || ['0x' + (+pn).toString(16)])[0], n]);
    return { frames: window.__frames, gpTotalMs: Math.round(window.__gpTime),
      params: top, callers: Object.entries(window.__stk).sort((a, b) => b[1] - a[1]).slice(0, 5) };
  });
  out.wallMs = wall;
  out.gpShareOfWall = Math.round(100 * out.gpTotalMs / wall) + '%';
  console.log(JSON.stringify(out, null, 1));
  await b.close().catch(() => {}); process.exit(0);
})().catch((e) => { console.log('DRIVER ' + e); process.exit(1); });
