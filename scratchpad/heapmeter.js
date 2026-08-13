// Read the wasm heap break from JS and watch it grow as a document does.
//
// Now that _emscripten_get_sbrk_ptr is exported, usage is a plain memory read: no Python,
// no blocking, so it works even while the app is busy -- which is exactly what the two
// previous attempts to find the 2 GB wall could not do.
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
const used = (p) => p.evaluate(() => {
  const m = window.fcInstance;
  try {
    const ptr = m._emscripten_get_sbrk_ptr();
    return { usedMB: +(m.HEAPU32[ptr >> 2] / 1048576).toFixed(1),
             capMB: Math.round(m.HEAPU8.buffer.byteLength / 1048576) };
  } catch (e) { return { usedMB: -1, capMB: -1, err: String(e).slice(0, 60) }; }
}).catch(() => null);
(async () => {
  const b = await puppeteer.launch({ executablePath: CHROME, headless: false, defaultViewport: null,
    args: ['--no-sandbox','--use-gl=angle','--use-angle=metal','--window-size=1400,900'],
    protocolTimeout: 3600000, userDataDir: '/tmp/fc-heapmeter' });
  const p = (await b.pages())[0];
  await p.goto(URL, { waitUntil: 'domcontentloaded', timeout: 300000 });
  const t0 = Date.now();
  while (Date.now() - t0 < 300000) { if (await p.evaluate(() => !!(window.fcInstance && window.fcInstance._malloc))) break; await sl(1000); }
  for (let i=0;i<40;i++){ await sl(3000); await run(p,'import sys,FreeCAD\nsys.__stderr__.write("RDY %d\\n"%len(FreeCAD.__unit_test__))\nsys.__stderr__.flush()\n'); await sl(1200);
    const m=[...(await readLog(p)).matchAll(/RDY (\d+)/g)].pop(); if(m&&+m[1]>0) break; }

  const base = await used(p);
  console.log('after boot: ' + JSON.stringify(base));
  if (!base || base.usedMB < 0) { console.log('sbrk export not visible -- ' + JSON.stringify(base)); await b.close(); process.exit(0); }

  await run(p, 'import sys, FreeCAD as App\nApp.newDocument("Heap")\nsys.__stderr__.write("D ok\\n")\nsys.__stderr__.flush()\n');
  await sl(3000);
  console.log('empty document: ' + JSON.stringify(await used(p)));

  // 200 solids at a time; the meter is read WHILE the batch runs, from JS
  for (const n of [200, 200, 400, 800]) {
    const t = Date.now();
    run(p, `
import sys
import FreeCAD as App
d = App.getDocument("Heap")
for i in range(${n}):
    b = d.addObject("Part::Box", "B"); b.Length=5; b.Width=5; b.Height=5
    b.Placement.Base = App.Vector((i%40)*6, (i//40)*6, 0)
d.recompute()
sys.__stderr__.write("ADDED %d\\n" % len(d.Objects)); sys.__stderr__.flush()
`).catch(() => {});
    let done = false, peak = 0;
    for (let w = 0; w < 240 && !done; w++) {
      await sl(2000);
      const u = await used(p);                      // works even while python runs
      if (u && u.usedMB > peak) peak = u.usedMB;
      try { const l = (await readLog(p)).match(/ADDED \d+/g) || []; done = l.length >= 1 && l[l.length-1].includes(String(n === 200 ? '' : '')) && true; } catch (e) {}
      if (done) break;
    }
    const u = await used(p);
    const objs = (((await readLog(p)).match(/ADDED (\d+)/g) || []).pop() || '?');
    console.log(`+${n} solids -> ${objs}, used=${u ? u.usedMB : '?'}MB / ${u ? u.capMB : '?'}MB, peak seen ${peak}MB (${((Date.now()-t)/1000).toFixed(0)}s)`);
    if (u && u.usedMB > u.capMB - 200) { console.log('  -> approaching the ceiling, stopping'); break; }
  }
  console.log('alive: ' + await p.evaluate(() => !!(window.fcInstance && window.fcInstance._malloc)).catch(() => false));
  await b.close().catch(()=>{}); process.exit(0);
})().catch((e)=>{console.log('DRIVER '+String(e).slice(0,200));process.exit(0);});
