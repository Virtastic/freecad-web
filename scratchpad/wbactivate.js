// First-activation check for EVERY workbench, with each one's error attributed.
//
// Gui.activateWorkbench() returns False (it does not raise) when a workbench's
// Initialize() throws, so a probe that only catches exceptions reports success while the
// user sees a click that does nothing. Only the FIRST attempt is meaningful: a failed
// Initialize often leaves enough behind that the second call succeeds.
//
// Usage: node scratchpad/wbactivate.js [url]
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

async function runAwait(p, code, re, timeoutMs) {
  await run(p, code);
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    await sl(1500);
    let log;
    try { log = await readLog(p); } catch (e) { return { dead: String(e).slice(0, 120) }; }
    const m = log.match(re);
    if (m) return { log, m };
  }
  return { timeout: true };
}

(async () => {
  const b = await puppeteer.launch({ executablePath: CHROME, headless: false, defaultViewport: null,
    args: ['--no-sandbox', '--use-gl=angle', '--use-angle=metal', '--window-size=1300,850'],
    protocolTimeout: 3600000, userDataDir: '/tmp/fc-wbact' });
  const p = (await b.pages())[0];
  await p.goto(URL, { waitUntil: 'domcontentloaded', timeout: 300000 });
  const t0 = Date.now();
  while (Date.now() - t0 < 300000) {
    if (await p.evaluate(() => !!(window.fcInstance && window.fcInstance._malloc))) break;
    await sl(1000);
  }
  let names = [];
  for (let i = 0; i < 60; i++) {
    await sl(3000);
    const r = await runAwait(p, `
import sys, FreeCADGui as Gui
sys.__stderr__.write("WA LIST " + ",".join(Gui.listWorkbenches()) + "|END\\n"); sys.__stderr__.flush()
`, /WA LIST ([^\n|]*)\|END/, 8000);
    if (r.m && r.m[1]) { names = r.m[1].split(',').filter(Boolean); break; }
  }
  console.log(`PLAN ${names.length} workbenches`);

  for (const w of names) {
    const py = `
import sys, traceback
import FreeCADGui as Gui
sys.__stderr__.write("WA >>> ${w}\\n"); sys.__stderr__.flush()
try:
    if Gui.activeWorkbench().name() == ${JSON.stringify(w)}:
        sys.__stderr__.write("WA ${w} ALREADY-ACTIVE\\n")
    else:
        r = Gui.activateWorkbench(${JSON.stringify(w)})
        sys.__stderr__.write("WA ${w} %s\\n" % ("ok" if r else "FAILED"))
except Exception as e:
    sys.__stderr__.write("WA ${w} EXC %s\\n" % str(e)[:120])
sys.__stderr__.flush()
`;
    const re = new RegExp('WA ' + w + ' (ok|FAILED|EXC|ALREADY-ACTIVE)');
    const r = await runAwait(p, py, re, 120000);
    if (r.dead) { console.log(`${w.padEnd(24)} PAGE DIED`); break; }
    if (r.timeout) { console.log(`${w.padEnd(24)} TIMEOUT`); continue; }
    const verdict = r.m[1];
    console.log(`${w.padEnd(24)} ${verdict}`);
    if (verdict === 'FAILED' || verdict === 'EXC') {
      // the reason is whatever FreeCAD printed between the marker and the verdict
      const seg = r.log.slice(r.log.lastIndexOf('WA >>> ' + w), r.log.lastIndexOf('WA ' + w + ' '));
      const why = seg.split('\n').map((l) => l.replace(/\{[\d.]+s\}\s*/, '').replace(/\x1b\[[0-9;]*m/g, '').trim())
        .filter((l) => l && !l.startsWith('WA ') && !l.startsWith('Traceback'));
      for (const l of why.slice(-6)) console.log('      ' + l.slice(0, 150));
    }
  }
  console.log('DONE');
  await b.close().catch(() => {}); process.exit(0);
})().catch((e) => { console.log('DRIVER ' + String(e).slice(0, 200)); process.exit(0); });
