// True interactive frame rate: the drag is driven from INSIDE the page, one pointermove
// per animation frame, which is what a real 60 Hz mouse produces. Driving it over CDP
// from node measured the injection round-trip instead (the main thread sat 68% idle).
// Asserts the camera actually moved -- a handler that swallows the event would otherwise
// look like a perfect score.
const puppeteer = require('puppeteer-core');
const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
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
    protocolTimeout: 2400000, userDataDir: '/tmp/fc-truedrag' });
  const p = (await b.pages())[0];
  await p.goto('http://localhost:8791/index.html', { waitUntil: 'domcontentloaded', timeout: 300000 });
  const t0 = Date.now();
  while (Date.now() - t0 < 300000) { if (await p.evaluate(() => !!(window.fcInstance && window.fcInstance._malloc))) break; await sl(1000); }
  await sl(9000);

  await p.evaluate(() => {
    window.__f = [];
    const P = WebGL2RenderingContext.prototype, clear = P.clear;
    P.clear = function (m) { if (m & this.COLOR_BUFFER_BIT) window.__f.push(performance.now()); return clear.apply(this, arguments); };
    // Qt puts its canvas in a shadow root and listens for POINTER events.
    window.__canvas = (function find(root) {
      const c = root.querySelector && root.querySelector('canvas');
      if (c) return c;
      const all = (root.querySelectorAll ? root.querySelectorAll('*') : []);
      for (const el of all) { if (el.shadowRoot) { const r = find(el.shadowRoot); if (r) return r; } }
      return null;
    })(document);
  });

  for (const MODEL of MODELS) {
    await run(p, ['import sys, FreeCAD as App, FreeCADGui as Gui',
      'd=App.openDocument("/freecad/share/examples/' + MODEL + '.FCStd")', 'Gui.updateGui()',
      'av=Gui.ActiveDocument.ActiveView', 'av.viewAxonometric(); av.fitAll(); Gui.updateGui()',
      'sys.__stderr__.write("VP-OPEN ' + MODEL + '\\n"); sys.__stderr__.flush()'].join('\n'));
    if (!await waitFor(p, 'VP-OPEN ' + MODEL, 900000)) { console.log(MODEL + ' open timed out'); continue; }
    await sl(3000);

    const before = await p.evaluate(() => {
      const d = document.getElementById('log'); return d ? d.textContent.length : 0;
    });
    await run(p, 'import FreeCADGui as Gui, sys\n' +
      'c=Gui.ActiveDocument.ActiveView.getCameraNode()\n' +
      'sys.__stderr__.write("CAM0 %s\\n" % (tuple(c.orientation.getValue().getValue()),))\n');
    await sl(800);

    const res = await p.evaluate(async () => {
      const cv = window.__canvas; if (!cv) return { err: 'no canvas' };
      const r = cv.getBoundingClientRect();
      const cx = r.left + r.width / 2, cy = r.top + r.height / 2;
      const ev = (type, x, y, btn) => cv.dispatchEvent(new PointerEvent(type, {
        pointerId: 1, pointerType: 'mouse', bubbles: true, cancelable: true, composed: true,
        clientX: x, clientY: y, button: btn === undefined ? 0 : btn, buttons: btn === undefined ? 1 : btn,
      }));
      const raf = () => new Promise((ok) => requestAnimationFrame(ok));
      window.__f = [];
      ev('pointerdown', cx, cy, 1);
      const t0 = performance.now();
      for (let i = 0; i < 90; i++) {
        ev('pointermove', cx + 160 * Math.sin(i / 9), cy + 110 * Math.cos(i / 8), 1);
        await raf();
      }
      ev('pointerup', cx, cy, 0);
      const wall = performance.now() - t0;
      const f = window.__f.slice();
      const gaps = f.slice(1).map((v, i) => v - f[i]).sort((a, b) => a - b);
      return { frames: f.length, wall: Math.round(wall),
        fps: +(f.length / (wall / 1000)).toFixed(1),
        medianMs: gaps.length ? +gaps[gaps.length >> 1].toFixed(1) : 0,
        p95Ms: gaps.length ? +gaps[Math.floor(gaps.length * 0.95)].toFixed(1) : 0 };
    });
    await run(p, 'import FreeCADGui as Gui, sys\n' +
      'c=Gui.ActiveDocument.ActiveView.getCameraNode()\n' +
      'sys.__stderr__.write("CAM1 %s\\n" % (tuple(c.orientation.getValue().getValue()),))\n');
    await sl(800);
    const log = await p.evaluate(() => document.getElementById('log').textContent);
    const cams = log.match(/CAM[01] \([^)]*\)/g) || [];
    const moved = cams.length >= 2 && cams[cams.length - 2].slice(5) !== cams[cams.length - 1].slice(5);
    console.log(MODEL.padEnd(12) + ' ' + JSON.stringify(res) + '  cameraMoved=' + moved);
    await run(p, 'App.closeDocument(App.ActiveDocument.Name)');
    await sl(2000);
  }
  await b.close().catch(() => {}); process.exit(0);
})().catch((e) => { console.log('DRIVER ' + e); process.exit(1); });
