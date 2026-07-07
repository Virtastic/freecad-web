// Streaming boot diagnostic: boots the 291MB build, samples the on-page log +
// console every 20s for up to 8 min, reports whether fcInstance becomes ready
// and dumps any abort/error/Traceback. Port 8792 (cache server).
const puppeteer = require('puppeteer-core');
const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const ARGS = ['--no-sandbox','--disable-dev-shm-usage','--disable-gpu-sandbox',
  '--js-flags=--max-old-space-size=8192','--use-gl=angle','--use-angle=swiftshader',
  '--enable-features=SharedArrayBuffer','--ignore-gpu-blocklist'];
(async () => {
  const b = await puppeteer.launch({ executablePath: CHROME, headless: 'new', args: ARGS,
    protocolTimeout: 600000, userDataDir: '/tmp/fc-chrome-profile' });
  const page = await b.newPage();
  const con = [];
  page.on('console', m => con.push(m.text()));
  page.on('pageerror', e => con.push('[PAGEERROR] ' + e.message));
  const t0 = Date.now();
  await page.goto('http://localhost:8799/freecad-gui.html', { waitUntil: 'domcontentloaded', timeout: 60000 });
  for (let i = 0; i < 24; i++) {
    await new Promise(r => setTimeout(r, 20000));
    const secs = Math.round((Date.now() - t0) / 1000);
    let ready = false, logtail = '';
    try {
      ready = await page.evaluate(() => !!(window.fcInstance && window.fcInstance._malloc));
      logtail = await page.evaluate(() => { const e = document.getElementById('log'); return e ? e.innerText.split('\n').slice(-3).join(' | ') : '(no log el)'; });
    } catch (e) { logtail = '[eval-threw ' + String(e.message).slice(0,60) + ']'; }
    const bad = con.filter(l => /abort|RuntimeError|unreachable|Aborted|PAGEERROR|Traceback|No module/i.test(l));
    console.log(`[t=${secs}s] ready=${ready} log="${logtail.slice(0,150)}"` + (bad.length ? `\n   ERR: ${[...new Set(bad)].slice(-3).join(' :: ').slice(0,300)}` : ''));
    if (ready) { console.log('BOOT-OK at ' + secs + 's'); break; }
    if (bad.some(l=>/abort|unreachable|Aborted/i.test(l))) { console.log('BOOT-ABORTED'); break; }
  }
  await b.close().catch(()=>{});
})().catch(e => { console.error('DIAG-ERR', e.message); process.exit(1); });
