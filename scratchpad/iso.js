// Isolation probe: run a Python snippet (arg1) with per-step flush, reusing the
// warm Chrome profile so boot is fast. Reads the log even if wasm later traps.
const puppeteer = require('puppeteer-core');
const CHROME = process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';  // set CHROME_PATH to run off macOS
const ARGS = ['--no-sandbox','--disable-dev-shm-usage','--disable-gpu-sandbox',
  '--js-flags=--max-old-space-size=8192','--use-gl=angle','--use-angle=swiftshader',
  '--enable-features=SharedArrayBuffer','--ignore-gpu-blocklist','--window-size=1400,900'];
const PY = process.argv[2];
(async () => {
  const b = await puppeteer.launch({ executablePath: CHROME, headless: 'new', args: ARGS, protocolTimeout: 300000, userDataDir: '/tmp/fc-chrome-profile' });
  const page = await b.newPage();
  const errs = [];
  page.on('pageerror', e => errs.push('[PAGEERROR] '+String(e.message).slice(0,140)));
  page.on('console', m => { const t=m.text(); if(/abort|unreachable|RuntimeError|Aborted/.test(t)) errs.push('[con] '+t.slice(0,140)); });
  await page.goto('http://localhost:8799/freecad-gui.html', { waitUntil:'domcontentloaded', timeout:120000 });
  await page.waitForFunction(() => window.fcInstance && window.fcInstance._malloc, { timeout: 480000, polling: 2000 });
  await new Promise(r => setTimeout(r, 12000));
  try {
    await page.evaluate((code) => {
      const m = window.fcInstance;
      const n = new TextEncoder().encode(code).length + 1;
      const p = m._malloc(n); m.stringToUTF8(code, p, n);
      try { m._fcweb_run_python(p); } finally { m._free(p); }
    }, PY);
  } catch (e) { errs.push('[EVAL-THREW] '+String(e.message).slice(0,80)); }
  await new Promise(r => setTimeout(r, 5000));
  let log = '';
  try { log = await page.evaluate(() => document.getElementById('log').innerText); } catch(e){ log='[log-read-failed]'; }
  console.log(log.split('\n').filter(l => /STEP|WBS|WB-|OK|FAIL|Error|Traceback/.test(l)).slice(-40).join('\n'));
  if (errs.length) console.log('--- errs ---\n'+[...new Set(errs)].slice(-8).join('\n'));
  await b.close().catch(()=>{});
})();
