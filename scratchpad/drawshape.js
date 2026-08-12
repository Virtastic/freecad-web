// What ARE the 4270 draws? Mode, vertex count, and whether consecutive draws share
// state. If most are tiny batches with identical state, they can be merged; if they are
// large, the count is irreducible and the cost is elsewhere.
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
(async () => {
  const b = await puppeteer.launch({ executablePath: CHROME, headless: false, defaultViewport: null,
    args: ['--no-sandbox', '--use-gl=angle', '--use-angle=metal', '--window-size=1400,900'],
    protocolTimeout: 2400000, userDataDir: '/tmp/fc-drawshape' });
  const p = (await b.pages())[0];
  await p.goto('http://localhost:8791/index.html', { waitUntil: 'domcontentloaded', timeout: 300000 });
  const t0 = Date.now();
  while (Date.now() - t0 < 300000) { if (await p.evaluate(() => !!(window.fcInstance && window.fcInstance._malloc))) break; await sl(1000); }
  await sl(9000);
  await run(p, ['import sys, FreeCAD as App, FreeCADGui as Gui',
    'd=App.openDocument("/freecad/share/examples/' + MODEL + '.FCStd")', 'Gui.updateGui()',
    'av=Gui.ActiveDocument.ActiveView', 'av.viewAxonometric(); av.fitAll(); Gui.updateGui()',
    'sys.__stderr__.write("OPEN\\n")'].join('\n'));
  await pw(p, 'OPEN', 900000); await sl(2500);

  await p.evaluate(() => {
    window.__d = { modes: {}, sizes: {}, total: 0, sameStateRuns: [], progSwitches: 0, frames: 0 };
    const P = WebGL2RenderingContext.prototype;
    const MODE = { 0: 'POINTS', 1: 'LINES', 2: 'LINE_LOOP', 3: 'LINE_STRIP', 4: 'TRIANGLES',
                   5: 'TRIANGLE_STRIP', 6: 'TRIANGLE_FAN' };
    let lastKey = null, run = 0, lastProg = null;
    const bucket = (n) => (n <= 4 ? String(n) : n <= 12 ? '5-12' : n <= 48 ? '13-48' : n <= 256 ? '49-256' : '257+');
    const up = P.useProgram;
    P.useProgram = function (pr) { if (pr !== lastProg) { window.__d.progSwitches++; lastProg = pr; } return up.apply(this, arguments); };
    const da = P.drawArrays;
    P.drawArrays = function (mode, first, count) {
      const d = window.__d;
      d.total++;
      d.modes[MODE[mode] || mode] = (d.modes[MODE[mode] || mode] || 0) + 1;
      d.sizes[bucket(count)] = (d.sizes[bucket(count)] || 0) + 1;
      // "same state" = same program and same primitive mode as the previous draw
      const key = mode + '|' + (lastProg && lastProg.__id !== undefined ? lastProg.__id : 'p');
      if (key === lastKey) { run++; } else { if (run) d.sameStateRuns.push(run + 1); run = 0; lastKey = key; }
      return da.apply(this, arguments);
    };
    const clear = P.clear;
    P.clear = function (m) { if (m & this.COLOR_BUFFER_BIT) window.__d.frames++; return clear.apply(this, arguments); };
  });
  const c = await p.evaluate(() => { const h = document.getElementById('qt-shadow-container');
    const cv = h && h.shadowRoot && h.shadowRoot.querySelector('canvas');
    const r = (cv || document.body).getBoundingClientRect();
    return { x: r.x + r.width * 0.55, y: r.y + r.height * 0.5 }; });
  await p.evaluate(() => { const d = window.__d; d.modes = {}; d.sizes = {}; d.total = 0; d.frames = 0; d.sameStateRuns = []; d.progSwitches = 0; });
  await p.mouse.move(c.x, c.y); await p.mouse.down({ button: 'middle' });
  for (let i = 1; i <= 20; i++) { await p.mouse.move(c.x + Math.round(80 * Math.sin(i / 6)), c.y + Math.round(50 * Math.cos(i / 5))); await sl(16); }
  await p.mouse.up({ button: 'middle' }); await sl(800);
  const d = await p.evaluate(() => {
    const x = window.__d;
    const runs = x.sameStateRuns.sort((a, b) => a - b);
    return { frames: x.frames, total: x.total, perFrame: Math.round(x.total / Math.max(1, x.frames)),
      modes: x.modes, sizes: x.sizes, progSwitchesPerFrame: Math.round(x.progSwitches / Math.max(1, x.frames)),
      medianRunOfSameState: runs.length ? runs[runs.length >> 1] : 0,
      runsOver8: runs.filter((r) => r > 8).length };
  });
  console.log(JSON.stringify(d, null, 1));
  await b.close().catch(() => {}); process.exit(0);
})().catch((e) => { console.log('DRIVER ' + String(e).slice(0, 200)); process.exit(1); });
