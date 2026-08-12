// Can the 2-vertex LINE_STRIP draws be merged? They can iff consecutive ones use the same
// buffer, contiguous vertex ranges, and have NO other GL call between them (any call could
// change state). Measures exactly that, and what GL calls do appear in between.
const puppeteer = require('puppeteer-core');
const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
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
    protocolTimeout: 2400000, userDataDir: '/tmp/fc-linemerge' });
  const p = (await b.pages())[0];
  await p.goto('http://localhost:8791/index.html', { waitUntil: 'domcontentloaded', timeout: 300000 });
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
    window.__m = { pairs: 0, contiguous: 0, between: {}, runs: [], nBetween: 0 };
    let prev = null, run = 1, sinceDraw = [];
    // record every GL call name so we can see what lands between two line draws
    for (const k of Object.getOwnPropertyNames(P)) {
      let f; try { f = P[k]; } catch (e) { continue; }
      if (typeof f !== 'function' || k === 'drawArrays') continue;
      P[k] = function () { sinceDraw.push(k); return f.apply(this, arguments); };
    }
    const da = P.drawArrays;
    P.drawArrays = function (mode, first, count) {
      const m = window.__m;
      const isSeg = (mode === this.LINE_STRIP && count === 2);
      if (isSeg && prev) {
        m.pairs++;
        const clean = sinceDraw.length === 0;
        const contig = clean && first === prev.first + prev.count;
        if (contig) { m.contiguous++; run++; }
        else { if (run > 1) m.runs.push(run); run = 1;
          if (!clean) { m.nBetween++; for (const c of sinceDraw.slice(0, 3)) m.between[c] = (m.between[c] || 0) + 1; } }
      }
      prev = isSeg ? { first, count } : null;
      sinceDraw = [];
      return da.apply(this, arguments);
    };
  });
  const c = await p.evaluate(() => { const h = document.getElementById('qt-shadow-container');
    const cv = h && h.shadowRoot && h.shadowRoot.querySelector('canvas');
    const r = (cv || document.body).getBoundingClientRect();
    return { x: r.x + r.width * 0.55, y: r.y + r.height * 0.5 }; });
  await p.mouse.move(c.x, c.y); await p.mouse.down({ button: 'middle' });
  for (let i = 1; i <= 12; i++) { await p.mouse.move(c.x + i * 5, c.y + i * 3); await sl(16); }
  await p.mouse.up({ button: 'middle' }); await sl(800);
  const m = await p.evaluate(() => {
    const x = window.__m, r = x.runs.sort((a, b) => a - b);
    return { segmentPairs: x.pairs, contiguousAndClean: x.contiguous,
      pctMergeable: Math.round(100 * x.contiguous / Math.max(1, x.pairs)),
      brokenByOtherCalls: x.nBetween, topCallsBetween: Object.entries(x.between).sort((a, b) => b[1] - a[1]).slice(0, 6),
      medianRun: r.length ? r[r.length >> 1] : 0, maxRun: r.length ? r[r.length - 1] : 0, runCount: r.length };
  });
  console.log(JSON.stringify(m, null, 1));
  await b.close().catch(() => {}); process.exit(0);
})().catch((e) => { console.log('DRIVER ' + String(e).slice(0, 200)); process.exit(1); });
