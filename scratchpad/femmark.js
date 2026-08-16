const __RT = require('path').resolve(__dirname, '..');  // repo root (was a hardcoded home dir)
// Boot + fire FEMExample open. Markers persist server-side via sync-XHR (/mark),
// so the tab need not survive — just boot and start the open. Retries boot.
const fs = require('fs');
const { execSync } = require('child_process');
const puppeteer = require('puppeteer-core');
const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
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
(async () => {
  for (let attempt = 1; attempt <= 8; attempt++) {
    let b;
    try {
      b = await puppeteer.launch({ executablePath: CHROME, headless:'new', args:ARGS, protocolTimeout:600000, userDataDir: PROFILE });
      const page = await b.newPage();
      await page.goto('http://localhost:8799/freecad-gui.html', { waitUntil:'domcontentloaded', timeout:120000 });
      await page.waitForFunction(() => window.fcInstance && window.fcInstance._malloc, { timeout: 300000, polling: 2500 });
      console.error('[attempt '+attempt+' booted, firing FEM open]');
      await new Promise(r=>setTimeout(r,10000));
      // fire the open; markers stream to server via sync-XHR. Don't need result.
      page.evaluate((code) => {
        const m = window.fcInstance;
        const n = new TextEncoder().encode(code).length + 1;
        const p = m._malloc(n); m.stringToUTF8(code, p, n);
        try { m._fcweb_run_python(p); } catch(e){} finally { try{m._free(p);}catch(_){} }
      }, PY).catch(()=>{});
      await new Promise(r=>setTimeout(r,25000)); // let markers flush server-side
      console.error('[attempt '+attempt+' done]');
      await b.close().catch(()=>{});
      return; // booted successfully; markers captured server-side
    } catch(e) {
      console.error('[attempt '+attempt+' boot-crash: '+String(e.message).slice(0,50)+']');
      try { await b.close(); } catch(_){}
      execSync("pkill -9 -f 'Google Chrome' 2>/dev/null || true");
      await new Promise(r=>setTimeout(r,3000));
    }
  }
  console.error('ALL BOOT ATTEMPTS FAILED');
})();
