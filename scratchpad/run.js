// Resilient single-probe runner: boots the 291MB build and runs a Python file
// (arg1 = path). Retries the whole boot up to 3x on renderer crashes
// (TargetCloseError) which are common at this wasm size in headless Chrome.
// Prints the filtered on-page log. Port 8799.
const fs = require('fs');
const puppeteer = require('puppeteer-core');
const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const ARGS = ['--no-sandbox','--disable-dev-shm-usage','--disable-gpu-sandbox',
  '--js-flags=--max-old-space-size=8192','--use-gl=angle','--use-angle=swiftshader',
  '--enable-features=SharedArrayBuffer','--ignore-gpu-blocklist','--window-size=1400,900',
  '--disable-backgrounding-occluded-windows','--disable-renderer-backgrounding'];
const PY = fs.readFileSync(process.argv[2], 'utf8');
// Key the Chrome profile (wasm code cache) to the built wasm's mtime so a NEW
// build always fetches fresh 256MB data (the server marks it immutable, so a
// shared profile would serve a stale/mismatched .data), while re-runs of the
// SAME build reuse the warm compile cache.
let PROFILE = '/tmp/fc-chrome-profile';
try {
  const mt = Math.floor(fs.statSync('/Users/mstavridis/Downloads/FreeCAD-Web/play-gui/FreeCAD.wasm').mtimeMs);
  PROFILE = '/tmp/fc-chrome-profile-' + mt;
} catch (e) {}

async function once() {
  const b = await puppeteer.launch({ executablePath: CHROME, headless: 'new', args: ARGS,
    protocolTimeout: 600000, userDataDir: PROFILE });
  try {
    const page = await b.newPage();
    const errs = [];
    page.on('pageerror', e => errs.push('[PAGEERROR] ' + String(e.message).slice(0,140)));
    page.on('console', m => { const t = m.text(); if (/abort|unreachable|RuntimeError|Aborted/.test(t)) errs.push('[con] ' + t.slice(0,140)); });
    await page.goto('http://localhost:8799/freecad-gui.html', { waitUntil: 'domcontentloaded', timeout: 120000 });
    await page.waitForFunction(() => window.fcInstance && window.fcInstance._malloc, { timeout: 540000, polling: 2500 });
    await new Promise(r => setTimeout(r, 12000));
    try {
      await page.evaluate((code) => {
        const m = window.fcInstance;
        const n = new TextEncoder().encode(code).length + 1;
        const p = m._malloc(n); m.stringToUTF8(code, p, n);
        try { m._fcweb_run_python(p); } finally { m._free(p); }
      }, PY);
    } catch (e) { errs.push('[EVAL-THREW] ' + String(e.message).slice(0,80)); }
    await new Promise(r => setTimeout(r, 6000));
    let log = '';
    try { log = await page.evaluate(() => document.getElementById('log').innerText); } catch (e) { log = '[log-read-failed]'; }
    return { log, errs };
  } finally { await b.close().catch(()=>{}); }
}

(async () => {
  for (let attempt = 1; attempt <= 3; attempt++) {
    try {
      const { log, errs } = await once();
      console.log(log.split('\n').filter(l => /STEP|WBS|EX-|OK|FAIL|Error|Traceback|version/.test(l)).slice(-50).join('\n'));
      if (errs.length) console.log('--- errs ---\n' + [...new Set(errs)].slice(-10).join('\n'));
      return;
    } catch (e) {
      console.error(`[attempt ${attempt} crashed: ${String(e.message).slice(0,80)}]`);
      require('child_process').execSync("pkill -9 -f 'Google Chrome' 2>/dev/null || true");
      await new Promise(r => setTimeout(r, 3000));
    }
  }
  console.error('ALL ATTEMPTS FAILED');
  process.exit(1);
})();
