// What a browser without JSPI (Firefox, Safari today) sees on the production site.
const puppeteer = require('puppeteer-core');
const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const sl = (ms) => new Promise((r) => setTimeout(r, ms));
(async () => {
  const b = await puppeteer.launch({ executablePath: CHROME, headless: false,
    defaultViewport: null, args: ['--no-sandbox', '--use-gl=angle', '--use-angle=metal', '--window-size=1200,800'],
    protocolTimeout: 1200000, userDataDir: '/tmp/fc-nojspi' });
  const p = (await b.pages())[0];
  const errs = [];
  p.on('pageerror', (e) => errs.push('PAGEERR ' + String(e).slice(0, 200)));
  p.on('console', (m) => { if (m.type() === 'error') errs.push('CON ' + m.text().slice(0, 200)); });
  await p.evaluateOnNewDocument(() => { try { delete WebAssembly.Suspending; delete WebAssembly.promising; } catch (e) {} });
  await p.goto('https://freecad.virtastic.app/', { waitUntil: 'domcontentloaded', timeout: 600000 });
  await sl(150000);
  const state = await p.evaluate(() => ({
    hasSuspending: typeof WebAssembly.Suspending,
    instance: !!(window.fcInstance && window.fcInstance._malloc),
    bodyText: (document.body.innerText || '').replace(/\s+/g, ' ').slice(0, 400),
  }));
  console.log(JSON.stringify(state, null, 1));
  console.log('--- errors ---\n' + errs.slice(0, 6).join('\n'));
  await b.close().catch(() => {}); process.exit(0);
})().catch((e) => { console.log('DRIVER ' + e); process.exit(0); });
