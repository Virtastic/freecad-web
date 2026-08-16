const __RT = require('path').resolve(__dirname, '..');  // repo root (was a hardcoded home dir)
// Capture FCWEB-RC/FCWEB-VP markers LIVE via console events so they survive a
// renderer crash on the FEM trap. Prints the tail of collected markers on exit.
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
import FreeCAD as App
print("VP-OPEN-BEGIN"); sys.stdout.flush()
d = App.openDocument("/freecad/examples/FEMExample.FCStd")
print("VP-OPEN-DONE objs=%d" % len(d.Objects)); sys.stdout.flush()
`;
const collected = [];
function dump(tag) {
  const marks = collected.filter(l => /FCWEB-RC|VP-OPEN|Executing|RecomputeFeature/.test(l));
  console.log('=== '+tag+' : last 20 recompute markers ('+marks.length+' total) ===');
  console.log(marks.slice(-20).join('\n'));
}
(async () => {
  for (let attempt = 1; attempt <= 3; attempt++) {
    collected.length = 0;
    const b = await puppeteer.launch({ executablePath: CHROME, headless:'new', args:ARGS, protocolTimeout:600000, userDataDir: PROFILE });
    const page = await b.newPage();
    page.on('console', m => { const t = m.text(); if (/FCWEB-RC|FCWEB-VP|FCWEB-FR|VP-OPEN|Recompute|Executing/.test(t)) collected.push(t); });
    try {
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
      } catch(e){ collected.push('[EVAL-THREW] '+String(e.message).slice(0,50)); }
      await new Promise(r=>setTimeout(r,4000));
      dump('attempt '+attempt);
      await b.close().catch(()=>{});
      return;
    } catch(e) {
      // crash during boot or eval: still dump what we streamed
      dump('attempt '+attempt+' CRASHED('+String(e.message).slice(0,40)+')');
      if (collected.some(l=>/VP-OPEN-BEGIN/.test(l))) { await b.close().catch(()=>{}); return; }
      await b.close().catch(()=>{});
      require('child_process').execSync("pkill -9 -f 'Google Chrome' 2>/dev/null || true");
      await new Promise(r=>setTimeout(r,3000));
    }
  }
})();
