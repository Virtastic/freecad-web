// TechDraw runs hidden-line removal off the main thread. Checking edges in the same
// synchronous Python call that creates the view can only ever see zero -- the same trap
// as FreeCAD's 150 ms action timer. Create, then wait in the HARNESS, then check.
const puppeteer = require('puppeteer-core');
const fs = require('fs');
const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const sl = (ms) => new Promise((r) => setTimeout(r, ms));
const run = (p, c) => p.evaluate((c) => { const m = window.fcInstance;
  const n = new TextEncoder().encode(c).length + 1; const q = m._malloc(n); m.stringToUTF8(c, q, n);
  (window.fcRunPy || ((mm, pp) => { mm._fcweb_run_python(pp); mm._free(pp); }))(m, q); }, c);
const tail = async (p, re) => ((await p.evaluate(() => document.getElementById('log').textContent)).match(re) || []).pop() || '(none)';
(async () => {
  const b = await puppeteer.launch({ executablePath: CHROME, headless: false, defaultViewport: null,
    args: ['--no-sandbox', '--use-gl=angle', '--use-angle=metal', '--window-size=1300,850'],
    protocolTimeout: 1800000, userDataDir: '/tmp/fc-techdraw-' + Date.now() });
  const p = (await b.pages())[0];
  await p.goto(process.argv[2] || 'http://localhost:8792/index.html', { waitUntil: 'domcontentloaded', timeout: 300000 });
  const t0 = Date.now();
  while (Date.now() - t0 < 300000) { if (await p.evaluate(() => !!(window.fcInstance && window.fcInstance._malloc))) break; await sl(1000); }
  await sl(17000);
  await run(p, fs.readFileSync('/tmp/td_setup.py', 'utf8'));
  await sl(4000);
  console.log(await tail(p, /TDS [^\n]*/g));
  for (const t of [2, 5, 10, 20]) {
    await sl(t === 2 ? 2000 : (t === 5 ? 3000 : (t === 10 ? 5000 : 10000)));
    await run(p, fs.readFileSync('/tmp/td_check.py', 'utf8'));
    await sl(1200);
    console.log('t=+' + t + 's  ' + await tail(p, /TDC [^\n]*/g));
  }
  await b.close().catch(() => {}); process.exit(0);
})().catch((e) => { console.log('DRIVER ' + String(e).slice(0, 200)); process.exit(0); });
