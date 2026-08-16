const __RT = require('path').resolve(__dirname, '..');  // repo root (was a hardcoded home dir)
// Minimal: boot, open FEMExample, let the sync-XHR markers land server-side.
// No DOM reading — markers are in /tmp/fc-markers.log even if the tab crashes.
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
print("FCWEB-AR VP-OPEN-BEGIN"); sys.stdout.flush()
d = App.openDocument("/freecad/examples/FEMExample.FCStd")
print("FCWEB-AR VP-OPEN-DONE objs=%d" % len(d.Objects)); sys.stdout.flush()
`;
(async () => {
  for (let attempt = 1; attempt <= 5; attempt++) {
    let b;
    try {
      b = await puppeteer.launch({ executablePath: CHROME, headless:'new', args:ARGS, protocolTimeout:600000, userDataDir: PROFILE });
      const page = await b.newPage();
      await page.goto('http://localhost:8799/freecad-gui.html', { waitUntil:'domcontentloaded', timeout:120000 });
      await page.waitForFunction(() => window.fcInstance && window.fcInstance._malloc, { timeout: 540000, polling: 2500 });
      await new Promise(r=>setTimeout(r,12000));
      try {
        await page.evaluate((code) => {
          const m = window.fcInstance;
          const n = new TextEncoder().encode(code).length + 1;
          const p = m._malloc(n); m.stringToUTF8(code, p, n);
          try { m._fcweb_run_python(p); } finally { try{m._free(p);}catch(_){} }
        }, PY);
      } catch(e){ console.log('[EVAL-THREW] ' + String(e.message).slice(0,50)); }
      await new Promise(r=>setTimeout(r,4000));
      await b.close().catch(()=>{});
      console.log('attempt '+attempt+' completed (check /tmp/fc-markers.log)');
      return;
    } catch(e) {
      console.error('[attempt '+attempt+' boot-crashed: '+String(e.message).slice(0,50)+']');
      if (b) await b.close().catch(()=>{});
      require('child_process').execSync("pkill -9 -f 'Google Chrome' 2>/dev/null; find /tmp/fc-chrome-profile-* -maxdepth 1 -name 'Singleton*' -delete 2>/dev/null || true");
      await new Promise(r=>setTimeout(r,3000));
    }
  }
})();
