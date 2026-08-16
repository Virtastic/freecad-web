// Generic post-boot Python probe with auto-retry on renderer crash.
// Usage: node probe.js '<python>' [waitMs]
const puppeteer = require('puppeteer-core');
const CHROME = process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';  // set CHROME_PATH to run off macOS
const PY = process.argv[2];
const ARGS = ['--no-sandbox','--disable-dev-shm-usage','--disable-gpu-sandbox',
  '--js-flags=--max-old-space-size=8192','--use-gl=angle','--use-angle=swiftshader',
  '--enable-features=SharedArrayBuffer','--ignore-gpu-blocklist','--window-size=1400,900'];

async function once() {
  const b = await puppeteer.launch({ executablePath: CHROME, headless: 'new', args: ARGS, protocolTimeout: 300000 });
  try {
    const page = await b.newPage();
    await page.setViewport({ width: 1400, height: 900 });
    const lines = [];
    page.on('pageerror', e => lines.push('[PAGEERROR] ' + e.message));
    await page.goto('http://localhost:8791/', { waitUntil: 'domcontentloaded', timeout: 60000 });
    await page.waitForFunction(() => window.fcInstance && window.fcInstance._malloc, { timeout: 180000, polling: 3000 });
    await new Promise(r => setTimeout(r, 12000));
    await page.evaluate((code) => {
      const m = window.fcInstance;
      const n = new TextEncoder().encode(code).length + 1;
      const p = m._malloc(n); m.stringToUTF8(code, p, n);
      try { m._fcweb_run_python(p); } finally { m._free(p); }
    }, PY);
    await new Promise(r => setTimeout(r, 6000));
    const log = await page.evaluate(() => document.getElementById('log').innerText);
    await page.screenshot({ path: '/tmp/fc-probe.png' }).catch(()=>{});
    console.log(log.split('\n').filter(l => /PROBE|FAIL|MISSING|Error|Traceback|DONE|OK|SCANRES/.test(l)).join('\n'));
    if (lines.length) console.log(lines.slice(-10).join('\n'));
    return true;
  } finally { await b.close().catch(()=>{}); }
}
(async () => {
  for (let i = 0; i < 3; i++) {
    try { await once(); return; }
    catch (e) { console.error('[retry '+i+'] '+String(e).slice(0,80)); await new Promise(r=>setTimeout(r,2000)); }
  }
  process.exit(1);
})();
