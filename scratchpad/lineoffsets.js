// Are consecutive 2-vertex line draws contiguous in one buffer (mergeable into a single
// GL_LINES draw), or does the emulation rewrite the same temp region every time?
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
    protocolTimeout: 2400000, userDataDir: '/tmp/fc-lineoffsets' });
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
    window.__o = { firsts: {}, sameBuf: 0, diffBuf: 0, contig: 0, n: 0, bufIds: new Set(), subData: 0, dataPerSeg: 0 };
    let nextId = 1, curBuf = null, prev = null;
    const bb = P.bindBuffer;
    P.bindBuffer = function (t, buf) { if (t === this.ARRAY_BUFFER) { curBuf = buf;
      if (buf && buf.__id === undefined) buf.__id = nextId++; } return bb.apply(this, arguments); };
    const bsd = P.bufferSubData; P.bufferSubData = function () { window.__o.subData++; return bsd.apply(this, arguments); };
    const bd = P.bufferData; P.bufferData = function () { window.__o.dataPerSeg++; return bd.apply(this, arguments); };
    const da = P.drawArrays;
    P.drawArrays = function (mode, first, count) {
      if (mode === this.LINE_STRIP && count === 2) {
        const o = window.__o; o.n++;
        o.firsts[first] = (o.firsts[first] || 0) + 1;
        o.bufIds.add(curBuf && curBuf.__id);
        if (prev) { if (prev.buf === (curBuf && curBuf.__id)) { o.sameBuf++;
            if (first === prev.first + 2) o.contig++; } else o.diffBuf++; }
        prev = { buf: curBuf && curBuf.__id, first };
      } else prev = null;
      return da.apply(this, arguments);
    };
  });
  const c = await p.evaluate(() => { const h = document.getElementById('qt-shadow-container');
    const cv = h && h.shadowRoot && h.shadowRoot.querySelector('canvas');
    const r = (cv || document.body).getBoundingClientRect();
    return { x: r.x + r.width * 0.55, y: r.y + r.height * 0.5 }; });
  await p.mouse.move(c.x, c.y); await p.mouse.down({ button: 'middle' });
  for (let i = 1; i <= 10; i++) { await p.mouse.move(c.x + i * 5, c.y + i * 3); await sl(16); }
  await p.mouse.up({ button: 'middle' }); await sl(800);
  console.log(JSON.stringify(await p.evaluate(() => {
    const o = window.__o;
    const f = Object.entries(o.firsts).sort((a, b) => b[1] - a[1]).slice(0, 5);
    return { segments: o.n, distinctBuffers: o.bufIds.size, sameBufferPairs: o.sameBuf,
      contiguousPairs: o.contig, topFirstOffsets: f, bufferDataCalls: o.dataPerSeg, bufferSubDataCalls: o.subData };
  }), null, 1));
  await b.close().catch(() => {}); process.exit(0);
})().catch((e) => { console.log('DRIVER ' + String(e).slice(0, 200)); process.exit(1); });
