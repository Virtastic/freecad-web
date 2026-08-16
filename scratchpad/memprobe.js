const puppeteer = require('puppeteer-core');
const fs = require('fs');
const CHROME = process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';  // set CHROME_PATH to run off macOS
const sl = (ms) => new Promise((r) => setTimeout(r, ms));
const CODE = fs.readFileSync('/tmp/memprobe.py', 'utf8');
(async () => {
  const errs = [];
  const b = await puppeteer.launch({ executablePath: CHROME, headless: false, defaultViewport: null,
    args: ['--no-sandbox', '--use-gl=angle', '--use-angle=metal', '--window-size=1300,850'],
    protocolTimeout: 2400000, userDataDir: '/tmp/fc-mem' });
  const p = (await b.pages())[0];
  p.on('pageerror', (e) => errs.push('PAGEERR ' + String(e).slice(0, 200)));
  await p.goto('http://localhost:8791/index.html', { waitUntil: 'domcontentloaded', timeout: 300000 });
  const t0 = Date.now();
  while (Date.now() - t0 < 300000) { if (await p.evaluate(() => !!(window.fcInstance && window.fcInstance._malloc))) break; await sl(1000); }
  await sl(9000);
  await p.evaluate((c) => { const m = window.fcInstance; const n = new TextEncoder().encode(c).length + 1;
    const q = m._malloc(n); m.stringToUTF8(c, q, n);
    (window.fcRunPy || ((mm, pp) => { mm._fcweb_run_python(pp); mm._free(pp); }))(m, q); }, CODE);
  const t1 = Date.now(); let log = '';
  while (Date.now() - t1 < 1500000) {
    log = await p.evaluate(() => { const e = document.getElementById('log'); return e ? e.textContent : ''; });
    if (/MP-END|MP-EXC|MP-.*FAILED/.test(log)) break;
    const dead = await p.evaluate(() => !!(window.fcInstance && window.fcInstance.__crashed)).catch(() => true);
    if (dead === true && false) break;
    await sl(4000);
  }
  console.log(log.split('\n').filter((l) => /MP-|memory|Memory|abort|Abort|OOM/.test(l)).slice(-14).join('\n'));
  console.log('--- page errors ---\n' + errs.slice(0, 4).join('\n'));
  await b.close().catch(() => {}); process.exit(0);
})().catch((e) => { console.log('DRIVER ' + e); process.exit(0); });
