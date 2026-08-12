const puppeteer = require('puppeteer-core');
const fs = require('fs');
const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const sl = (ms) => new Promise((r) => setTimeout(r, ms));
const CODE = fs.readFileSync(process.argv[2], 'utf8');
const MARK = process.argv[3] || 'PROBE';
(async () => {
  const b = await puppeteer.launch({ executablePath: CHROME, headless: false, defaultViewport: null,
    args: ['--no-sandbox', '--use-gl=angle', '--use-angle=metal', '--window-size=1200,800'],
    protocolTimeout: 1200000, userDataDir: '/tmp/fc-pyprobe' });
  const p = (await b.pages())[0];
  await p.goto('http://localhost:8791/index.html', { waitUntil: 'domcontentloaded', timeout: 300000 });
  const t0 = Date.now();
  while (Date.now() - t0 < 300000) { if (await p.evaluate(() => !!(window.fcInstance && window.fcInstance._malloc))) break; await sl(1000); }
  await sl(11000);
  await p.evaluate((c) => { const m = window.fcInstance;
    const n = new TextEncoder().encode(c).length + 1; const q = m._malloc(n); m.stringToUTF8(c, q, n);
    (window.fcRunPy || ((mm, pp) => { mm._fcweb_run_python(pp); mm._free(pp); }))(m, q); }, CODE);
  const t1 = Date.now(); let out = '(no output)';
  while (Date.now() - t1 < 120000) {
    const t = await p.evaluate(() => document.getElementById('log').textContent);
    const m = t.match(new RegExp(MARK + '[^\\n]*', 'g'));
    if (m) { out = m[m.length - 1]; break; }
    await sl(1000);
  }
  console.log(out);
  await b.close().catch(() => {}); process.exit(0);
})().catch((e) => { console.log('DRIVER ' + String(e).slice(0, 200)); process.exit(0); });
