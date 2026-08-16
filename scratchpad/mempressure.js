// Does the memory-pressure monitor actually fire, and does it save the user's work?
// Lowers the thresholds at runtime so the check is reached without building a 1.6 GB model.
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
    protocolTimeout: 1200000, userDataDir: '/tmp/fc-mempress2' });
  const p = (await b.pages())[0];
  const notes = [];
  await p.goto(URL, { waitUntil: 'domcontentloaded', timeout: 300000 });
  const t0 = Date.now();
  while (Date.now() - t0 < 300000) { if (await p.evaluate(() => !!(window.fcInstance && window.fcInstance._malloc))) break; await sl(1000); }
  for (let i=0;i<40;i++){ await sl(3000); await run(p,'import sys,FreeCAD\nsys.__stderr__.write("RDY %d\\n"%len(FreeCAD.__unit_test__))\nsys.__stderr__.flush()\n'); await sl(1200);
    const m=[...(await readLog(p)).matchAll(/RDY (\d+)/g)].pop(); if(m&&+m[1]>0) break; }

  console.log('heap reader works: fcwebHeapUsedMB() = '
    + await p.evaluate(() => (typeof window.fcwebHeapUsedMB === 'function' ? window.fcwebHeapUsedMB() : 'ABSENT')));

  // capture what the user would be told
  await p.evaluate(() => {
    window.__notes = [];
    const orig = window.fcwebNotify;
    window.fcwebNotify = function (msg, kind) { window.__notes.push(kind + ': ' + msg); if (orig) try { orig(msg, kind); } catch (e) {} };
  });

  // a document with unsaved work, then thresholds low enough that the current heap trips them
  await run(p, `
import sys
import FreeCAD as App
d = App.newDocument("Pressure")
b = d.addObject("Part::Box", "B"); b.Length = 11; b.Width = 12; b.Height = 13
d.recompute()
sys.__stderr__.write("WORK volume=%.1f saved=%s\\n" % (b.Shape.Volume, d.isSaved())); sys.__stderr__.flush()
`);
  await sl(4000);
  console.log(((await readLog(p)).match(/WORK [^\n]*/g) || ['no work line']).pop());

  await p.evaluate(() => { window.MEM_WARN = 0; });   // not enough on its own: the vars are closure-scoped
  // so instead drive the exported check by faking a high reading through the same path:
  const fired = await p.evaluate(async () => {
    // lower the threshold instead of lying about the heap: the real reading (about 300 MB
    // of 2048) then counts as pressure, and nothing in the runtime is disturbed
    window.__fcwebMemWarn = 0.05;
    await new Promise((r) => setTimeout(r, 8000));   // let the 5s interval tick
    window.__fcwebMemWarn = 0.80;
    return window.__notes.slice();
  });
  console.log('notifications raised: ' + (fired.length ? fired.join(' || ') : 'NONE'));

  await sl(4000);
  await run(p, `
import sys, os
rec = "/home/web_user/.fcweb-autosave"
files = sorted(os.listdir(rec)) if os.path.isdir(rec) else []
sys.__stderr__.write("AUTOSAVED %d %s\\n" % (len(files), files[:3])); sys.__stderr__.flush()
`);
  await sl(3000);
  console.log(((await readLog(p)).match(/AUTOSAVED [^\n]*/g) || ['no autosave line']).pop());
  console.log('alive: ' + await p.evaluate(() => !!(window.fcInstance && window.fcInstance._malloc)).catch(() => false));
  await b.close().catch(()=>{}); process.exit(0);
})().catch((e)=>{console.log('DRIVER '+String(e).slice(0,200));process.exit(0);});
