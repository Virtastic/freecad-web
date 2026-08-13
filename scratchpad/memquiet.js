// The memory monitor must stay SILENT during normal heavy use.
// It polls every 5 s and force-saves at 80%; a false positive would interrupt a user and
// write recovery copies for no reason. Open the heaviest bundled examples and assert it
// says nothing at all.
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
(async () => {
  const b = await puppeteer.launch({ executablePath: CHROME, headless: false, defaultViewport: null,
    args: ['--no-sandbox','--use-gl=angle','--use-angle=metal','--window-size=1400,900'],
    protocolTimeout: 2400000, userDataDir: '/tmp/fc-memquiet' });
  const p = (await b.pages())[0];
  await p.goto(URL, { waitUntil: 'domcontentloaded', timeout: 300000 });
  const t0 = Date.now();
  while (Date.now() - t0 < 300000) { if (await p.evaluate(() => !!(window.fcInstance && window.fcInstance._malloc))) break; await sl(1000); }
  for (let i=0;i<40;i++){ await sl(3000); await run(p,'import sys,FreeCAD\nsys.__stderr__.write("RDY %d\\n"%len(FreeCAD.__unit_test__))\nsys.__stderr__.flush()\n'); await sl(1200);
    const m=[...(await readLog(p)).matchAll(/RDY (\d+)/g)].pop(); if(m&&+m[1]>0) break; }

  await p.evaluate(() => {
    window.__mem = [];
    const orig = window.fcwebNotify;
    window.fcwebNotify = function (msg, kind) {
      if (/memory|MB of the 2 GB|nearly full/i.test(String(msg))) window.__mem.push(kind + ': ' + msg);
      if (orig) try { orig(msg, kind); } catch (e) {}
    };
  });

  // the heaviest examples, opened one after another and left open (worst case for the poll)
  for (const ex of ['BIMExample', 'FEMExample', 'AssemblyExample']) {
    await run(p, `
import sys, os
import FreeCAD as App, FreeCADGui as Gui
d = os.path.join(App.getResourceDir(), "examples")
f = [x for x in os.listdir(d) if "${ex}".lower().replace("example","") in x.lower()]
if f:
    App.openDocument(os.path.join(d, f[0]))
    Gui.updateGui()
    sys.__stderr__.write("OPENED ${ex} docs=%d\\n" % len(App.listDocuments()))
else:
    sys.__stderr__.write("OPENED ${ex} notfound\\n")
sys.__stderr__.flush()
`);
    await sl(20000);   // several poll ticks with the document loaded
    const line = ((await readLog(p)).match(/OPENED [^\n]*/g) || []).pop();
    const heap = await p.evaluate(() => (window.fcwebHeapUsedMB ? window.fcwebHeapUsedMB() : -1));
    console.log(`${line}  heap=${heap}MB`);
  }
  await sl(15000);     // idle, more ticks
  const notes = await p.evaluate(() => window.__mem);
  console.log('memory notifications during normal use: ' + (notes.length ? notes.join(' | ') : 'NONE (correct)'));
  await run(p, 'import sys, os\nr="/home/web_user/.fcweb-autosave"\nsys.__stderr__.write("RECOVERY %s\\n" % (sorted(os.listdir(r)) if os.path.isdir(r) else "no dir"))\nsys.__stderr__.flush()\n');
  await sl(3000);
  console.log(((await readLog(p)).match(/RECOVERY [^\n]*/g) || ['?']).pop());
  console.log('final heap: ' + await p.evaluate(() => window.fcwebHeapUsedMB()) + 'MB of 2048');
  await b.close().catch(()=>{}); process.exit(0);
})().catch((e)=>{console.log('DRIVER '+String(e).slice(0,200));process.exit(0);});
