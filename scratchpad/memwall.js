// Where is the 2 GB wall, and what happens when a user hits it?
//
// The heap is a fixed 2 GB (ALLOW_MEMORY_GROWTH=0). "There is a hard wall" has been in the
// notes for weeks without a number next to it, which is not good enough to ship on: a user
// needs to know whether that is 10k objects or 100. This grows a document in steps,
// reporting heap use, until it either reaches the target or dies -- and if it dies, whether
// it died civilly (message, work recoverable) or vanished.
const puppeteer = require('puppeteer-core');
const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const sl = (ms) => new Promise((r) => setTimeout(r, ms));
const URL = process.argv[2] || 'http://localhost:8792/index.html';
const run = (p, code) => p.evaluate((c) => {
  const m = window.fcInstance;
  const n = new TextEncoder().encode(c).length + 1; const q = m._malloc(n); m.stringToUTF8(c, q, n);
  (window.fcRunPy || ((mm, pp) => { mm._fcweb_run_python(pp); mm._free(pp); }))(m, q);
}, code);
const readLog = (p) => p.evaluate(() => document.getElementById('log').textContent);
const last = async (p, re) => { const m = (await readLog(p)).match(re) || []; return m.length ? m[m.length - 1] : ''; };
(async () => {
  const b = await puppeteer.launch({ executablePath: CHROME, headless: false, defaultViewport: null,
    args: ['--no-sandbox','--use-gl=angle','--use-angle=metal','--window-size=1400,900'],
    protocolTimeout: 3600000, userDataDir: '/tmp/fc-memwall2' });
  const p = (await b.pages())[0];
  const errs = [];
  p.on('pageerror', (e) => errs.push(String(e).slice(0, 120)));
  await p.goto(URL, { waitUntil: 'domcontentloaded', timeout: 300000 });
  const t0 = Date.now();
  while (Date.now() - t0 < 300000) { if (await p.evaluate(() => !!(window.fcInstance && window.fcInstance._malloc))) break; await sl(1000); }
  for (let i=0;i<40;i++){ await sl(3000); await run(p,'import sys,FreeCAD\nsys.__stderr__.write("RDY %d\\n"%len(FreeCAD.__unit_test__))\nsys.__stderr__.flush()\n'); await sl(1200);
    const m=[...(await readLog(p)).matchAll(/RDY (\d+)/g)].pop(); if(m&&+m[1]>0) break; }

  // buffer.byteLength is USELESS here: with ALLOW_MEMORY_GROWTH=0 the 2 GB is
  // pre-allocated, so it reads 2048 from the first instant. The used portion is the sbrk
  // break; fall back to "unknown" rather than reporting the ceiling as if it were usage.
  const heap = () => p.evaluate(() => {
    const m = window.fcInstance;
    let usedMB = -1;
    try { if (typeof m._sbrk === 'function') usedMB = Math.round(m._sbrk(0) / 1048576); } catch (e) {}
    if (usedMB < 0) { try { if (typeof m._emscripten_get_sbrk_ptr === 'function')
      usedMB = Math.round(m.HEAPU32[m._emscripten_get_sbrk_ptr() >> 2] / 1048576); } catch (e) {} }
    return { usedMB, capMB: (m && m.HEAPU8) ? Math.round(m.HEAPU8.buffer.byteLength / 1048576) : -1 };
  }).catch(() => null);

  await run(p, 'import sys, FreeCAD as App\nApp.newDocument("Mem")\nsys.__stderr__.write("DOC ok\\n")\nsys.__stderr__.flush()\n');
  await sl(3000);
  console.log('baseline heap: ' + JSON.stringify(await heap()));

  // add solids in batches; each Part::Box with a shape costs real memory
  let total = 0;
  for (let batch = 1; batch <= 40; batch++) {
    const before = Date.now();
    await run(p, `
import sys
import FreeCAD as App
d = App.getDocument("Mem")
try:
    for i in range(250):
        b = d.addObject("Part::Box", "B")
        b.Length = 5; b.Width = 5; b.Height = 5
        b.Placement.Base = App.Vector((i % 50) * 6, (i // 50) * 6, 0)
    d.recompute()
    sys.__stderr__.write("BATCH ok objects=%d\\n" % len(d.Objects))
except Exception as e:
    sys.__stderr__.write("BATCH EXC %s\\n" % str(e)[:100])
sys.__stderr__.flush()
`);
    let line = '';
    for (let w = 0; w < 60 && !line; w++) {
      await sl(2000);
      try { line = (await last(p, /BATCH [^\n]*/g)); } catch (e) { line = 'PAGE GONE'; break; }
      const seen = ((await readLog(p)).match(/BATCH [^\n]*/g) || []).length;
      if (seen < batch) line = '';
    }
    if (line === 'PAGE GONE' || !line) { console.log(`batch ${batch}: PAGE DIED or no response`); break; }
    total += 250;
    const h = await heap();
    console.log(`batch ${batch}: ${line.trim()} used=${h ? h.usedMB : '?'}MB/${h ? h.capMB : '?'}MB (+${((Date.now()-before)/1000).toFixed(1)}s)`);
    if (line.includes('EXC')) { console.log('  -> FreeCAD refused further objects (civil failure)'); break; }
    if (h && h.usedMB > 0 && h.usedMB > h.capMB - 150) { console.log('  -> within 150MB of the ceiling'); break; }
  }
  const aliveAfter = await p.evaluate(() => !!(window.fcInstance && window.fcInstance._malloc)).catch(() => false);
  console.log('instance alive at end: ' + aliveAfter);
  console.log('page errors: ' + (errs.length ? errs.slice(0, 3).join(' | ') : 'none'));
  await p.screenshot({ path: '/tmp/memwall.png' }).catch(() => {});
  await b.close().catch(()=>{}); process.exit(0);
})().catch((e)=>{console.log('DRIVER '+String(e).slice(0,200));process.exit(0);});
