// Dump the real attribute layout at a 2-vertex LINE_STRIP draw: which attributes are
// enabled, their size/type/stride/offset, and the byteLength of the upload feeding them.
const puppeteer = require('puppeteer-core');
const CHROME = process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';  // set CHROME_PATH to run off macOS
const sl = (ms) => new Promise((r) => setTimeout(r, ms));
const run = (p, c) => p.evaluate((c) => { const m = window.fcInstance;
  const n = new TextEncoder().encode(c).length + 1; const q = m._malloc(n); m.stringToUTF8(c, q, n);
  (window.fcRunPy || ((mm, pp) => { mm._fcweb_run_python(pp); mm._free(pp); }))(m, q); }, c);
const pw = async (p, mk, ms) => { const t0 = Date.now();
  while (Date.now() - t0 < ms) { try { if (await p.evaluate((k) =>
    document.getElementById('log').textContent.includes(k), mk)) return true; } catch (e) {} await sl(400); } return false; };
(async () => {
  const b = await puppeteer.launch({ executablePath: CHROME, headless: false, defaultViewport: null,
    args: ['--no-sandbox', '--use-gl=angle', '--use-angle=metal', '--window-size=1400,900'],
    protocolTimeout: 2400000, userDataDir: '/tmp/fc-attrdump' });
  const p = (await b.pages())[0];
  await p.goto('http://localhost:8791/index.html?nolinebatch=1', { waitUntil: 'domcontentloaded', timeout: 300000 });
  const t0 = Date.now();
  while (Date.now() - t0 < 300000) { if (await p.evaluate(() => !!(window.fcInstance && window.fcInstance._malloc))) break; await sl(1000); }
  await sl(9000);
  await run(p, ['import sys, FreeCAD as App, FreeCADGui as Gui',
    'd=App.openDocument("/freecad/share/examples/BIMExample.FCStd")', 'Gui.updateGui()',
    'av=Gui.ActiveDocument.ActiveView', 'av.viewAxonometric(); av.fitAll(); Gui.updateGui()',
    'sys.__stderr__.write("OPEN\\n")'].join('\n'));
  await pw(p, 'OPEN', 900000); await sl(2500);
  await p.evaluate(() => {
    const P = WebGL2RenderingContext.prototype;
    window.__a = { samples: [], counts: {} };
    const attrs = {}, on = {}; let sub = null, arr = null;
    const rb = P.bindBuffer; P.bindBuffer = function (t, b) { if (t === this.ARRAY_BUFFER) arr = b; return rb.apply(this, arguments); };
    const rv = P.vertexAttribPointer; P.vertexAttribPointer = function (i, size, type, norm, stride, off) {
      attrs[i] = { size, type, stride, off }; return rv.apply(this, arguments); };
    const re = P.enableVertexAttribArray; P.enableVertexAttribArray = function (i) { on[i] = true; return re.apply(this, arguments); };
    const rd = P.disableVertexAttribArray; P.disableVertexAttribArray = function (i) { on[i] = false; return rd.apply(this, arguments); };
    const rs = P.bufferSubData; P.bufferSubData = function (t, off, d) {
      sub = { off, len: d && d.byteLength }; return rs.apply(this, arguments); };
    const da = P.drawArrays;
    P.drawArrays = function (mode, first, count) {
      if (mode === this.LINE_STRIP && count === 2) {
        const enabled = Object.keys(on).filter((k) => on[k]).map((k) => ({ i: +k, ...attrs[k] }));
        const key = JSON.stringify({ e: enabled, first, sub });
        window.__a.counts[key] = (window.__a.counts[key] || 0) + 1;
        if (window.__a.samples.length < 3) window.__a.samples.push({ enabled, first, sub, buf: !!arr });
      }
      return da.apply(this, arguments);
    };
  });
  const c = await p.evaluate(() => { const h = document.getElementById('qt-shadow-container');
    const cv = h && h.shadowRoot && h.shadowRoot.querySelector('canvas');
    const r = (cv || document.body).getBoundingClientRect();
    return { x: r.x + r.width * 0.55, y: r.y + r.height * 0.5 }; });
  await p.mouse.move(c.x, c.y); await p.mouse.down({ button: 'middle' });
  for (let i = 1; i <= 8; i++) { await p.mouse.move(c.x + i * 5, c.y + i * 3); await sl(16); }
  await p.mouse.up({ button: 'middle' }); await sl(800);
  console.log(JSON.stringify(await p.evaluate(() => ({
    samples: window.__a.samples,
    distinctLayouts: Object.keys(window.__a.counts).length,
    top: Object.entries(window.__a.counts).sort((a, b) => b[1] - a[1]).slice(0, 2).map(([k, v]) => [JSON.parse(k), v]),
  })), null, 1));
  await b.close().catch(() => {}); process.exit(0);
})().catch((e) => { console.log('DRIVER ' + String(e).slice(0, 200)); process.exit(1); });
