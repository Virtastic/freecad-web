const __RT = require('path').resolve(__dirname, '..');  // repo root (was a hardcoded home dir)
// Capture the FULL wasm stack trace when FEMExample open traps.
const fs = require('fs');
const puppeteer = require('puppeteer-core');
const CHROME = process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';  // set CHROME_PATH to run off macOS
const ARGS = ['--no-sandbox','--disable-dev-shm-usage','--disable-gpu-sandbox',
  '--js-flags=--max-old-space-size=8192','--use-gl=angle','--use-angle=swiftshader',
  '--enable-features=SharedArrayBuffer','--ignore-gpu-blocklist'];
let PROFILE = '/tmp/fc-chrome-profile';
try { PROFILE = '/tmp/fc-chrome-profile-' + Math.floor(fs.statSync(__RT+'/play-gui/FreeCAD.wasm').mtimeMs); } catch(e){}
const PY = `
import sys
print("T begin"); sys.stdout.flush()
import FreeCAD as App
print("T open"); sys.stdout.flush()
d = App.openDocument("/freecad/examples/FEMExample.FCStd")
print("T opened %d" % len(d.Objects)); sys.stdout.flush()
`;
(async () => {
  const b = await puppeteer.launch({ executablePath: CHROME, headless:'new', args:ARGS, protocolTimeout:600000, userDataDir: PROFILE });
  const page = await b.newPage();
  const all = [];
  page.on('console', m => all.push(m.text()));
  page.on('pageerror', e => all.push('[PAGEERROR] ' + e.message + '\n' + (e.stack||'')));
  await page.goto('http://localhost:8799/freecad-gui.html', { waitUntil:'domcontentloaded', timeout:120000 });
  await page.waitForFunction(() => window.fcInstance && window.fcInstance._malloc, { timeout: 540000, polling: 2500 });
  await new Promise(r=>setTimeout(r,12000));
  try {
    await page.evaluate((code) => {
      const m = window.fcInstance;
      const n = new TextEncoder().encode(code).length + 1;
      const p = m._malloc(n); m.stringToUTF8(code, p, n);
      try { m._fcweb_run_python(p); } finally { m._free(p); }
    }, PY);
  } catch(e){ all.push('[EVAL-THREW] ' + e.message); }
  await new Promise(r=>setTimeout(r,5000));
  // dump everything mentioning stack/trap/wasm-function/Fem/ViewProvider/abort
  const interesting = all.filter(l => /wasm-function|unreachable|abort|RuntimeError|Fem|ViewProvider|Constraint|PostObject|Coin|stack|Aborted|\bat \b/i.test(l));
  console.log(interesting.join('\n').slice(-4000));
  await b.close().catch(()=>{});
})().catch(e=>{console.error('ERR',e.message);process.exit(1);});
