// Capture everything FreeCAD logs during the FIRST activation of a workbench.
// Usage: node scratchpad/camfirst.js [WorkbenchName] [url]
const puppeteer = require('puppeteer-core');
const CHROME = process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';  // set CHROME_PATH to run off macOS
const sl = (ms) => new Promise((r) => setTimeout(r, ms));
const WB = process.argv[2] || 'CAMWorkbench';
const URL = process.argv[3] || 'http://localhost:8792/index.html';

const run = (p, code) => p.evaluate((c) => {
  const m = window.fcInstance;
  const n = new TextEncoder().encode(c).length + 1; const q = m._malloc(n); m.stringToUTF8(c, q, n);
  (window.fcRunPy || ((mm, pp) => { mm._fcweb_run_python(pp); mm._free(pp); }))(m, q);
}, code);
const readLog = (p) => p.evaluate(() => document.getElementById('log').textContent);

(async () => {
  const b = await puppeteer.launch({ executablePath: CHROME, headless: false, defaultViewport: null,
    args: ['--no-sandbox', '--use-gl=angle', '--use-angle=metal', '--window-size=1300,850'],
    protocolTimeout: 1200000, userDataDir: '/tmp/fc-camfirst' });
  const p = (await b.pages())[0];
  await p.goto(URL, { waitUntil: 'domcontentloaded', timeout: 300000 });
  const t0 = Date.now();
  while (Date.now() - t0 < 300000) {
    if (await p.evaluate(() => !!(window.fcInstance && window.fcInstance._malloc))) break;
    await sl(1000);
  }
  for (let i = 0; i < 60; i++) {
    await sl(3000);
    await run(p, 'import sys, FreeCAD\nsys.__stderr__.write("CF READY %d\\n" % len(FreeCAD.__unit_test__))\nsys.__stderr__.flush()\n');
    await sl(1500);
    const l = await readLog(p);
    const m = [...l.matchAll(/CF READY (\d+)/g)].pop();
    if (m && Number(m[1]) > 0) break;
  }

  // everything FreeCAD prints during activation lands in the same log, so mark the window
  await run(p, `
import sys, traceback
import FreeCADGui as Gui, FreeCAD
sys.__stderr__.write("CF BEGIN\\n"); sys.__stderr__.flush()
try:
    r = Gui.activateWorkbench(${JSON.stringify(WB)})
    sys.__stderr__.write("CF RESULT %r active=%s\\n" % (r, Gui.activeWorkbench().name()))
except Exception as e:
    sys.__stderr__.write("CF EXC %s\\n" % traceback.format_exc()[-600:])
sys.__stderr__.write("CF END\\n"); sys.__stderr__.flush()
`);
  await sl(20000);
  const log = await readLog(p);
  const i = log.indexOf('CF BEGIN'); const j = log.indexOf('CF END');
  console.log(i >= 0 ? log.slice(i, j > i ? j + 8 : i + 4000) : '(no BEGIN marker; tail follows)\n' + log.slice(-3000));
  await b.close().catch(() => {}); process.exit(0);
})().catch((e) => { console.log('DRIVER ' + String(e).slice(0, 200)); process.exit(0); });
