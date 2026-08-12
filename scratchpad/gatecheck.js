// Two runs against the local server: JSPI removed (must refuse, must download nothing)
// and untouched (must still boot). The download assertion is the point -- the old
// failure was pulling 450 MB and then hanging.
const puppeteer = require('puppeteer-core');
const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const sl = (ms) => new Promise((r) => setTimeout(r, ms));

async function run(block) {
  const b = await puppeteer.launch({ executablePath: CHROME, headless: false,
    defaultViewport: null, args: ['--no-sandbox', '--use-gl=angle', '--use-angle=metal', '--window-size=1200,800'],
    protocolTimeout: 1200000, userDataDir: '/tmp/fc-gate-' + (block ? 'no' : 'yes') });
  const p = (await b.pages())[0];
  const heavy = [];
  p.on('response', (r) => { const u = r.url(); if (/FreeCAD\.(data|wasm|js)$/.test(u)) heavy.push(u.split('/').pop()); });
  if (block) {
    await p.evaluateOnNewDocument(() => { try { delete WebAssembly.Suspending; } catch (e) {} });
  }
  await p.goto('http://localhost:8791/index.html', { waitUntil: 'domcontentloaded', timeout: 300000 });
  if (block) { await sl(8000); } else {
    const t0 = Date.now();
    while (Date.now() - t0 < 300000) {
      if (await p.evaluate(() => !!(window.fcInstance && window.fcInstance._malloc))) break;
      await sl(1000);
    }
    await sl(5000);
  }
  const out = await p.evaluate(() => ({
    refused: !!window.__FC_UNSUPPORTED,
    booted: !!(window.fcInstance && window.fcInstance._malloc),
    text: (document.body.innerText || '').replace(/\s+/g, ' ').slice(0, 260),
  }));
  out.fetched = [...new Set(heavy)];
  await b.close().catch(() => {});
  return out;
}
(async () => {
  console.log('NO-JSPI  ' + JSON.stringify(await run(true), null, 1));
  console.log('NORMAL   ' + JSON.stringify(await run(false), null, 1));
  process.exit(0);
})().catch((e) => { console.log('DRIVER ' + e); process.exit(1); });
