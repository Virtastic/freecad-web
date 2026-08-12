const puppeteer = require('puppeteer-core');
const fs = require('fs');
const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const sl = (ms) => new Promise((r) => setTimeout(r, ms));
const grab = async (p, re) => ((await p.evaluate(() => document.getElementById('log').textContent)).match(re) || []);
(async () => {
  const b = await puppeteer.launch({ executablePath: CHROME, headless: false, defaultViewport: null,
    args: ['--no-sandbox', '--use-gl=angle', '--use-angle=metal', '--window-size=1300,850'],
    protocolTimeout: 1200000, userDataDir: '/tmp/fc-nativeinput' });
  const p = (await b.pages())[0];
  await p.goto('http://localhost:8792/index.html', { waitUntil: 'domcontentloaded', timeout: 300000 });
  const t0 = Date.now();
  while (Date.now() - t0 < 300000) { if (await p.evaluate(() => !!(window.fcInstance && window.fcInstance._malloc))) break; await sl(1000); }
  await sl(16000);
  p.evaluate((c) => { const m = window.fcInstance;
    const n = new TextEncoder().encode(c).length + 1; const q = m._malloc(n); m.stringToUTF8(c, q, n);
    (window.fcRunPy || ((mm, pp) => { mm._fcweb_run_python(pp); mm._free(pp); }))(m, q);
  }, fs.readFileSync('/tmp/nativeinput.py', 'utf8')).catch(() => {});
  await sl(6000);
  const lines = await grab(p, /NIN [^\n]*/g);
  console.log(lines.join('\n'));
  const ok = /btn 'OK' at (\d+),(\d+)/.exec(lines.join('\n'));
  if (ok) { console.log('clicking OK at ' + ok[1] + ',' + ok[2]); await p.mouse.click(+ok[1], +ok[2]); }
  await sl(5000);
  console.log((await grab(p, /NIN (INPUT RESULT|color|DONE)[^\n]*/g)).join('\n') || '(nothing after exec)');
  await p.screenshot({ path: '/tmp/nativeinput.png' });
  await b.close().catch(() => {}); process.exit(0);
})().catch((e) => { console.log('DRIVER ' + String(e).slice(0, 200)); process.exit(0); });
