const puppeteer = require('puppeteer-core');
const fs = require('fs');
const CHROME = process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';  // set CHROME_PATH to run off macOS
const sl = (ms) => new Promise((r) => setTimeout(r, ms));
const grab = async (p, re) => {
  const t = await p.evaluate(() => document.getElementById('log').textContent);
  return (t.match(re) || []);
};
(async () => {
  const b = await puppeteer.launch({ executablePath: CHROME, headless: false, defaultViewport: null,
    args: ['--no-sandbox', '--use-gl=angle', '--use-angle=metal', '--window-size=1300,850'],
    protocolTimeout: 1200000, userDataDir: '/tmp/fc-nativeexec' });
  const p = (await b.pages())[0];
  await p.goto('http://localhost:8792/index.html', { waitUntil: 'domcontentloaded', timeout: 300000 });
  const t0 = Date.now();
  while (Date.now() - t0 < 300000) { if (await p.evaluate(() => !!(window.fcInstance && window.fcInstance._malloc))) break; await sl(1000); }
  await sl(16000);
  p.evaluate((c) => { const m = window.fcInstance;
    const n = new TextEncoder().encode(c).length + 1; const q = m._malloc(n); m.stringToUTF8(c, q, n);
    (window.fcRunPy || ((mm, pp) => { mm._fcweb_run_python(pp); mm._free(pp); }))(m, q);
  }, fs.readFileSync('/tmp/nativeexec.py', 'utf8')).catch(() => {});
  await sl(6000);
  const btns = await grab(p, /NEX btn [^\n]*/g);
  console.log(btns.join('\n'));
  const called = (await grab(p, /NEX calling native[^\n]*/g)).length > 0;
  console.log('exec entered: ' + called + '  (if it suspended, the page is still responsive)');
  const alive = await p.evaluate(() => !!document.getElementById('log'));
  // click the real Qt "Yes" button on the canvas
  const m = /NEX btn 'Yes' at (\d+),(\d+)/.exec(btns.join('\n'));
  if (m) {
    console.log('clicking Yes at ' + m[1] + ',' + m[2]);
    await p.mouse.click(+m[1], +m[2]);
  } else { console.log('no Yes coords'); }
  await sl(5000);
  const res = await grab(p, /NEX RESULT [^\n]*/g);
  console.log('page responsive during modal: ' + alive);
  console.log(res.length ? res.join('\n') : 'RESULT: none (exec never returned)');
  await p.screenshot({ path: '/tmp/nativeexec.png' });
  await b.close().catch(() => {}); process.exit(0);
})().catch((e) => { console.log('DRIVER ' + String(e).slice(0, 200)); process.exit(0); });
