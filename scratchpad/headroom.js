// How much memory can the application actually still allocate at runtime?
//
// "The heap is a fixed 2 GB" has sat in the notes without a number beside it. The useful
// figure is not the ceiling but the HEADROOM: how much a document can still grow before
// allocation fails, and whether failure is civil (a Python MemoryError the app survives)
// or fatal (the instance dies and takes the user's work).
//
// Allocating in Python goes through the same wasm heap as everything else, so this
// measures the real thing without waiting on 3D view rebuilds.
const puppeteer = require('puppeteer-core');
const CHROME = process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';  // set CHROME_PATH to run off macOS
const sl = (ms) => new Promise((r) => setTimeout(r, ms));
const URL = process.argv[2] || 'http://localhost:8792/index.html';
const run = (p, code) => p.evaluate((c) => {
  const m = window.fcInstance;
  const n = new TextEncoder().encode(c).length + 1; const q = m._malloc(n); m.stringToUTF8(c, q, n);
  (window.fcRunPy || ((mm, pp) => { mm._fcweb_run_python(pp); mm._free(pp); }))(m, q);
}, code);
const readLog = (p) => p.evaluate(() => document.getElementById('log').textContent);
(async () => {
  const b = await puppeteer.launch({ executablePath: CHROME, headless: false, defaultViewport: null,
    args: ['--no-sandbox','--use-gl=angle','--use-angle=metal','--window-size=1400,900'],
    protocolTimeout: 3600000, userDataDir: '/tmp/fc-headroom' });
  const p = (await b.pages())[0];
  const errs = [];
  p.on('pageerror', (e) => errs.push(String(e).slice(0, 120)));
  await p.goto(URL, { waitUntil: 'domcontentloaded', timeout: 300000 });
  const t0 = Date.now();
  while (Date.now() - t0 < 300000) { if (await p.evaluate(() => !!(window.fcInstance && window.fcInstance._malloc))) break; await sl(1000); }
  for (let i=0;i<40;i++){ await sl(3000); await run(p,'import sys,FreeCAD\nsys.__stderr__.write("RDY %d\\n"%len(FreeCAD.__unit_test__))\nsys.__stderr__.flush()\n'); await sl(1200);
    const m=[...(await readLog(p)).matchAll(/RDY (\d+)/g)].pop(); if(m&&+m[1]>0) break; }

  // one call: grab 32 MB at a time until it fails, then report and RELEASE
  await run(p, `
import sys
blocks = []
mb = 0
err = ""
try:
    while mb < 4096:
        blocks.append(bytearray(32 * 1024 * 1024))
        mb += 32
except MemoryError:
    err = "MemoryError"
except Exception as e:
    err = type(e).__name__ + ": " + str(e)[:60]
sys.__stderr__.write("HEADROOM %d MB stopped_by=%s\\n" % (mb, err or "cap"))
sys.__stderr__.flush()
del blocks          # give it all back; the instance must stay usable afterwards
`);
  // the interpreter is blocked while this runs; poll patiently
  let line = '';
  for (let i = 0; i < 300 && !line; i++) {
    await sl(4000);
    try { line = ((await readLog(p)).match(/HEADROOM [^\n]*/g) || []).pop() || ''; }
    catch (e) { line = 'PAGE DIED: ' + String(e).slice(0, 80); break; }
  }
  console.log(line || 'no answer within 20 minutes');

  // did the app survive the squeeze?
  await sl(3000);
  let alive = false, worked = '';
  try {
    alive = await p.evaluate(() => !!(window.fcInstance && window.fcInstance._malloc));
    await run(p, `
import sys
import FreeCAD as App
d = App.newDocument("AfterSqueeze")
b = d.addObject("Part::Box", "B"); b.Length = 3; b.Width = 4; b.Height = 5
d.recompute()
sys.__stderr__.write("AFTER volume=%.1f\\n" % b.Shape.Volume); sys.__stderr__.flush()
`);
    for (let i = 0; i < 30 && !worked; i++) {
      await sl(2000);
      worked = ((await readLog(p)).match(/AFTER [^\n]*/g) || []).pop() || '';
    }
  } catch (e) { worked = 'unreachable'; }
  console.log('instance alive after: ' + alive + ' | modelling still works: ' + (worked || 'NO'));
  console.log('  (a box 3x4x5 must come back as 60.0)');
  console.log('page errors: ' + (errs.length ? errs.slice(0, 3).join(' | ') : 'none'));
  await b.close().catch(()=>{}); process.exit(0);
})().catch((e)=>{console.log('DRIVER '+String(e).slice(0,200));process.exit(0);});
