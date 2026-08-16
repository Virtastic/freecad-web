// How expensive is ONE frame? Real (trusted) CDP mouse events, pipelined so the driver's
// round-trip is not the limiter, and per-frame busy time measured inside the page:
// busy = last GL call of a frame - the clear that started it. `gap` is the observed
// interval; busy is what the app actually costs. Camera movement is asserted.
const puppeteer = require('puppeteer-core');
const CHROME = process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';  // set CHROME_PATH to run off macOS
const sl = (ms) => new Promise((r) => setTimeout(r, ms));
const run = (p, c) => p.evaluate((c) => { const m = window.fcInstance;
  const n = new TextEncoder().encode(c).length + 1; const q = m._malloc(n); m.stringToUTF8(c, q, n);
  (window.fcRunPy || ((mm, pp) => { mm._fcweb_run_python(pp); mm._free(pp); }))(m, q); }, c);
const waitFor = async (p, mark, ms) => { const t0 = Date.now();
  while (Date.now() - t0 < ms) { const t = await p.evaluate(() => (document.getElementById('log') || {}).textContent || '');
    if (t.includes(mark)) return true; await sl(500); } return false; };
const MODELS = process.argv.slice(2);
(async () => {
  const b = await puppeteer.launch({ executablePath: CHROME, headless: false, defaultViewport: null,
    args: ['--no-sandbox', '--use-gl=angle', '--use-angle=metal', '--window-size=1400,900'],
    protocolTimeout: 2400000, userDataDir: '/tmp/fc-framecost' });
  const p = (await b.pages())[0];
  const cdp = await p.target().createCDPSession();
  await p.goto('http://localhost:8791/index.html', { waitUntil: 'domcontentloaded', timeout: 300000 });
  const t0 = Date.now();
  while (Date.now() - t0 < 300000) { if (await p.evaluate(() => !!(window.fcInstance && window.fcInstance._malloc))) break; await sl(1000); }
  await sl(9000);
  await p.evaluate(() => {
    window.__fr = [];
    const P = WebGL2RenderingContext.prototype;
    const clear = P.clear;
    P.clear = function (m) {
      if (m & this.COLOR_BUFFER_BIT) { window.__fr.push({ t: performance.now(), end: 0, draws: 0 }); }
      return clear.apply(this, arguments);
    };
    ['drawArrays', 'drawElements', 'finish', 'flush', 'readPixels', 'blitFramebuffer'].forEach((nm) => {
      const o = P[nm]; if (!o) return;
      const isDraw = nm === 'drawArrays' || nm === 'drawElements';
      P[nm] = function () { const r = o.apply(this, arguments);
        const f = window.__fr[window.__fr.length - 1];
        if (f) { f.end = performance.now(); if (isDraw) f.draws++; }
        return r; };
    });
  });
  for (const MODEL of MODELS) {
    await run(p, ['import sys, FreeCAD as App, FreeCADGui as Gui',
      'd=App.openDocument("/freecad/share/examples/' + MODEL + '.FCStd")', 'Gui.updateGui()',
      'av=Gui.ActiveDocument.ActiveView', 'av.viewAxonometric(); av.fitAll(); Gui.updateGui()',
      'sys.__stderr__.write("VP-OPEN ' + MODEL + '\\n"); sys.__stderr__.flush()'].join('\n'));
    if (!await waitFor(p, 'VP-OPEN ' + MODEL, 900000)) { console.log(MODEL + ' open timed out'); continue; }
    await sl(2500);
    await run(p, 'import FreeCADGui as Gui, sys\nc=Gui.ActiveDocument.ActiveView.getCameraNode()\nsys.__stderr__.write("CAMA %s\\n" % (tuple(c.orientation.getValue().getValue()),))\n');
    await sl(700);
    await p.evaluate(() => { window.__fr = []; });
    const mv = (x, y, type, buttons) => cdp.send('Input.dispatchMouseEvent',
      { type, x, y, button: 'left', buttons, clickCount: 1 });
    await mv(700, 450, 'mousePressed', 1);
    const tStart = Date.now();
    // Sequential and awaited. Pipelining them lets Chrome coalesce the moves into two or
    // three events -- fast, but the camera never moves, so it measures nothing.
    for (let i = 0; i < 120; i++) {
      await mv(700 + Math.round(170 * Math.sin(i / 11)), 450 + Math.round(115 * Math.cos(i / 9)), 'mouseMoved', 1);
    }
    const wall = Date.now() - tStart;
    await mv(700, 450, 'mouseReleased', 0);
    const st = await p.evaluate(() => {
      // a clear with no draws after it is Qt clearing a UI surface, not a scene frame
      const f = window.__fr.filter((x) => x.draws > 0 && x.end > x.t);
      const busy = f.map((x) => x.end - x.t).sort((a, b) => a - b);
      const gaps = f.slice(1).map((x, i) => x.t - f[i].t).sort((a, b) => a - b);
      const pick = (a, q) => (a.length ? +a[Math.min(a.length - 1, Math.floor(a.length * q))].toFixed(1) : 0);
      const dr = f.map((x) => x.draws).sort((a, b) => a - b);
      return { frames: f.length, busyMedian: pick(busy, 0.5), busyP95: pick(busy, 0.95),
               gapMedian: pick(gaps, 0.5), drawsMedian: pick(dr, 0.5) };
    });
    await run(p, 'import FreeCADGui as Gui, sys\nc=Gui.ActiveDocument.ActiveView.getCameraNode()\nsys.__stderr__.write("CAMB %s\\n" % (tuple(c.orientation.getValue().getValue()),))\n');
    await sl(700);
    const log = await p.evaluate(() => document.getElementById('log').textContent);
    const a = (log.match(/CAMA \([^)]*\)/g) || []).pop(), bb = (log.match(/CAMB \([^)]*\)/g) || []).pop();
    console.log(MODEL.padEnd(18) + 'frames=' + String(st.frames).padStart(4) +
      '  busy median=' + String(st.busyMedian).padStart(6) + 'ms  p95=' + String(st.busyP95).padStart(6) +
      'ms  observed gap=' + String(st.gapMedian).padStart(6) + 'ms  wall=' + wall +
      'ms  cameraMoved=' + (a && bb && a.slice(5) !== bb.slice(5)));
    await run(p, 'App.closeDocument(App.ActiveDocument.Name)');
    await sl(2000);
  }
  await b.close().catch(() => {}); process.exit(0);
})().catch((e) => { console.log('DRIVER ' + e); process.exit(1); });
