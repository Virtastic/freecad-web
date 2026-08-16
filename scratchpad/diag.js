// Boot diagnostic: log crash/navigation/console events to find why the page dies.
const puppeteer = require('puppeteer-core');
const CHROME = process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';  // set CHROME_PATH to run off macOS
const ARGS = ['--no-sandbox','--disable-dev-shm-usage','--disable-gpu-sandbox',
  '--js-flags=--max-old-space-size=8192','--use-gl=angle','--use-angle=swiftshader',
  '--enable-features=SharedArrayBuffer','--ignore-gpu-blocklist','--window-size=1400,900'];
const Q = process.argv[2] || '';
(async () => {
  const b = await puppeteer.launch({ executablePath: CHROME, headless: 'new', args: ARGS, protocolTimeout: 300000 });
  const page = await b.newPage();
  page.on('console', m => { const t = m.text(); if (/error|Error|abort|RuntimeError|failed|Failed/.test(t)) console.log('[con]', t.slice(0,200)); });
  page.on('pageerror', e => console.log('[pageerror]', String(e).slice(0,200)));
  page.on('error', e => console.log('[CRASH]', String(e)));
  page.on('framenavigated', f => console.log('[nav]', f.url()));
  page.on('framedetached', () => console.log('[framedetached]'));
  await page.goto('http://localhost:8791/freecad-gui.html' + Q, { waitUntil: 'domcontentloaded', timeout: 60000 });
  for (let i = 0; i < 40; i++) {
    await new Promise(r => setTimeout(r, 5000));
    try {
      const s = await page.evaluate(() => ({
        fc: !!(window.fcInstance && window.fcInstance._malloc),
        log: (document.getElementById('log')||{innerText:''}).innerText.split('\n').slice(-3).join(' | ')
      }));
      console.log(`[t+${(i+1)*5}s] fc=${s.fc} :: ${s.log.slice(0,180)}`);
      if (s.fc) { console.log('BOOT-OK'); break; }
    } catch (e) { console.log(`[t+${(i+1)*5}s] EVAL-FAIL:`, String(e).slice(0,120)); }
  }
  await b.close().catch(()=>{});
})();
