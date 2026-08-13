const puppeteer = require('puppeteer-core');
const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const sl = (ms) => new Promise((r) => setTimeout(r, ms));
(async () => {
  const b = await puppeteer.launch({ executablePath: CHROME, headless: false, defaultViewport: null,
    args: ['--no-sandbox', '--use-gl=angle', '--use-angle=metal', '--window-size=1300,850'],
    protocolTimeout: 1200000, userDataDir: '/tmp/fc-pyem' });
  const p = (await b.pages())[0];
  await p.goto('http://localhost:8792/index.html', { waitUntil: 'domcontentloaded', timeout: 300000 });
  const t0 = Date.now();
  while (Date.now() - t0 < 300000) { if (await p.evaluate(() => !!(window.fcInstance && window.fcInstance._malloc))) break; await sl(1000); }
  await sl(14000);
  const r = await p.evaluate(() => {
    const m = window.fcInstance;
    const out = { type: typeof (m && m.PyEM_CountArgs), postRunLeft: (m && m.postRun && m.postRun.length) };
    try { out.sample = m.PyEM_CountArgs(1); } catch (e) { out.sample = 'EXC ' + e; }
    return out;
  });
  const log = await p.evaluate(() => document.getElementById('log').textContent);
  console.log('PYEM ' + JSON.stringify(r));
  console.log('LOGLINES ' + (log.match(/PyEM_CountArgs[^\n]*/g) || ['none']).join(' | '));
  await b.close().catch(() => {}); process.exit(0);
})().catch((e) => { console.log('DRIVER ' + String(e).slice(0, 200)); process.exit(0); });
