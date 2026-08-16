const puppeteer = require('puppeteer-core');
const CHROME = process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';  // set CHROME_PATH to run off macOS
const sl = (ms) => new Promise((r) => setTimeout(r, ms));
const run = (p, code) => p.evaluate((c) => {
  const m = window.fcInstance;
  const n = new TextEncoder().encode(c).length + 1; const q = m._malloc(n); m.stringToUTF8(c, q, n);
  (window.fcRunPy || ((mm, pp) => { mm._fcweb_run_python(pp); mm._free(pp); }))(m, q);
}, code);
const readLog = (p) => p.evaluate(() => document.getElementById('log').textContent);
(async () => {
  const b = await puppeteer.launch({ executablePath: CHROME, headless: false, defaultViewport: null,
    args: ['--no-sandbox','--use-gl=angle','--use-angle=metal','--window-size=1300,850'],
    protocolTimeout: 1200000, userDataDir: '/tmp/fc-csg' });
  const p = (await b.pages())[0];
  await p.goto('http://localhost:8792/index.html', { waitUntil: 'domcontentloaded', timeout: 300000 });
  const t0 = Date.now();
  while (Date.now() - t0 < 300000) { if (await p.evaluate(() => !!(window.fcInstance && window.fcInstance._malloc))) break; await sl(1000); }
  for (let i = 0; i < 40; i++) { await sl(3000); await run(p, 'import sys,FreeCAD\nsys.__stderr__.write("RDY %d\\n"%len(FreeCAD.__unit_test__))\nsys.__stderr__.flush()\n'); await sl(1200); const l = await readLog(p); const m=[...l.matchAll(/RDY (\d+)/g)].pop(); if (m && +m[1]>0) break; }
  await run(p, `
import sys, importCSG, FreeCAD
sys.__stderr__.write("CSGBEGIN\\n"); sys.__stderr__.flush()
open("/tmp/c.csg","w").write("cube(size = [10, 10, 10], center = false);\\n")
importCSG.printverbose = True
try:
    importCSG.open("/tmp/c.csg")
    d = FreeCAD.ActiveDocument
    sys.__stderr__.write("CSGOBJ %d %s\\n" % (len(d.Objects), [o.TypeId for o in d.Objects]))
except Exception as e:
    import traceback; sys.__stderr__.write("CSGEXC %s\\n" % traceback.format_exc()[-500:])
sys.__stderr__.write("CSGEND\\n"); sys.__stderr__.flush()
`);
  await sl(25000);
  const log = await readLog(p);
  const i = log.indexOf('CSGBEGIN'), j = log.indexOf('CSGEND');
  console.log(i>=0 ? log.slice(i, j>i?j+7:i+5000) : log.slice(-3000));
  await b.close().catch(()=>{}); process.exit(0);
})().catch((e)=>{console.log('DRIVER '+String(e).slice(0,200));process.exit(0);});
