const puppeteer = require('puppeteer-core');
const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const sl = (ms) => new Promise((r) => setTimeout(r, ms));
(async () => {
  const b = await puppeteer.launch({ executablePath: CHROME, headless: false, defaultViewport: null,
    args: ['--no-sandbox', '--use-gl=angle', '--use-angle=metal', '--window-size=1300,850'],
    protocolTimeout: 900000, userDataDir: '/tmp/fc-regression' });
  const p = (await b.pages())[0];
  await p.goto('https://freecad.virtastic.app/', { waitUntil: 'domcontentloaded', timeout: 300000 });
  const t0 = Date.now();
  while (Date.now() - t0 < 300000) { if (await p.evaluate(() => !!(window.fcInstance && window.fcInstance._malloc))) break; await sl(1000); }
  await sl(30000);
  await p.screenshot({ path: '/tmp/wedged.png' });
  // what does the FS hold from the OLD recovery scheme?
  console.log(JSON.stringify(await p.evaluate(() => {
    const m = window.fcInstance; const out = {};
    for (const d of ['/home/web_user/.FreeCAD/recovery', '/home/web_user/.fcweb-autosave', '/home/web_user/.FreeCAD']) {
      try { out[d] = m.FS.readdir(d).filter((f) => f !== '.' && f !== '..'); } catch (e) { out[d] = 'n/a'; }
    }
    return out;
  })));
  await b.close().catch(() => {}); process.exit(0);
})().catch((e) => { console.log('DRIVER ' + String(e).slice(0, 200)); process.exit(0); });
