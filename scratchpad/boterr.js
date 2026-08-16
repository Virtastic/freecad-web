const puppeteer = require('puppeteer-core');
const CHROME = process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';  // set CHROME_PATH to run off macOS
const sl = (ms) => new Promise((r) => setTimeout(r, ms));
(async () => {
  const errs = [];
  const b = await puppeteer.launch({ executablePath: CHROME, headless: false, defaultViewport: null,
    args: ['--no-sandbox', '--use-gl=angle', '--use-angle=metal', '--window-size=1200,800'],
    protocolTimeout: 1200000, userDataDir: '/tmp/fc-boterr' });
  const p = (await b.pages())[0];
  p.on('pageerror', (e) => errs.push('PAGEERR ' + String(e.message || e).slice(0, 300)));
  p.on('console', (m) => { if (m.type() === 'error') errs.push('CONSOLE ' + m.text().slice(0, 300)); });
  await p.goto('http://localhost:' + (process.argv[2] || '8792') + '/index.html',
    { waitUntil: 'domcontentloaded', timeout: 300000 });
  const t0 = Date.now();
  while (Date.now() - t0 < 300000) { if (await p.evaluate(() => !!(window.fcInstance && window.fcInstance._malloc))) break; await sl(1000); }
  await sl(20000);
  const log = await p.evaluate(() => document.getElementById('log').textContent);
  console.log(errs.slice(0, 8).join('\n') || '(no page errors)');
  console.log('--- dialog bridge: ' + ((log.match(/JSPI (blocking-dialog )?bridge[^\n]*/g) || ['(no bridge line)']).join(' | ')));
  console.log('--- storage: ' + ((log.match(/persistent storage[^\n]*/g) || ['(none)']).join(' | ')));
  await b.close().catch(() => {}); process.exit(0);
})().catch((e) => { console.log('DRIVER ' + String(e).slice(0, 200)); process.exit(0); });
