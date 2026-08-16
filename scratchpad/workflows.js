// Eight real CAD workflows end to end, each ending in a checkable number. Anything broken
// here is something a person hits in their first hour of building a part.
// TechDraw's edge count is re-checked after a wait: its hidden-line removal runs off the
// main thread, so a count taken in the same synchronous call is always zero.
const puppeteer = require('puppeteer-core');
const fs = require('fs');
const CHROME = process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';  // set CHROME_PATH to run off macOS
const sl = (ms) => new Promise((r) => setTimeout(r, ms));
const URL = process.argv[2] || 'http://localhost:8792/index.html';
const run = (p, c) => p.evaluate((c) => { const m = window.fcInstance;
  const n = new TextEncoder().encode(c).length + 1; const q = m._malloc(n); m.stringToUTF8(c, q, n);
  (window.fcRunPy || ((mm, pp) => { mm._fcweb_run_python(pp); mm._free(pp); }))(m, q); }, c);
(async () => {
  const errs = [];
  const b = await puppeteer.launch({ executablePath: CHROME, headless: false, defaultViewport: null,
    args: ['--no-sandbox', '--use-gl=angle', '--use-angle=metal', '--window-size=1300,850'],
    protocolTimeout: 2400000, userDataDir: '/tmp/fc-workflows-' + Date.now() });
  const p = (await b.pages())[0];
  p.on('pageerror', (e) => errs.push(String(e.message || e).slice(0, 120)));
  await p.goto(URL, { waitUntil: 'domcontentloaded', timeout: 300000 });
  const t0 = Date.now();
  while (Date.now() - t0 < 400000) { if (await p.evaluate(() => !!(window.fcInstance && window.fcInstance._malloc))) break; await sl(1000); }
  await sl(17000);
  await run(p, fs.readFileSync(__dirname + '/workflows.py', 'utf8'));
  const t1 = Date.now();
  while (Date.now() - t1 < 600000) {
    if ((await p.evaluate(() => document.getElementById('log').textContent)).includes('WF DONE')) break;
    await sl(2000);
  }
  await sl(4000);
  await run(p, fs.readFileSync('/tmp/wf_after.py', 'utf8'));
  await sl(3000);
  const log = await p.evaluate(() => document.getElementById('log').textContent);
  const lines = [...(log.match(/W[FA] [^\n]*/g) || [])];
  console.log(lines.join('\n'));
  const fails = lines.filter((l) => l.includes('FAIL')).length;
  console.log('---\n' + (lines.length - 1) + ' checks, ' + fails + ' failures, ' +
    errs.length + ' page errors');
  await b.close().catch(() => {}); process.exit(fails ? 1 : 0);
})().catch((e) => { console.log('DRIVER ' + String(e).slice(0, 200)); process.exit(1); });
