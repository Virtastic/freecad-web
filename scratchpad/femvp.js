const __RT = require('path').resolve(__dirname, '..');  // repo root (was a hardcoded home dir)
// Open FEMExample and dump the [FCWEB-VP] attach markers to find the last VP
// before the unreachable trap. Cache-safe profile. Port 8799.
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
(async () => {
  for (let attempt = 1; attempt <= 6; attempt++) {
    const b = await puppeteer.launch({ executablePath: CHROME, headless:'new', args:ARGS, protocolTimeout:600000, userDataDir: PROFILE });
    try {
      const page = await b.newPage();
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
      } catch(e){ console.log('[EVAL-THREW] ' + String(e.message).slice(0,60)); }
      await new Promise(r=>setTimeout(r,5000));
      let log='';
      try { log = await page.evaluate(() => document.getElementById('log').innerText); } catch(e){ log='[log-read-failed: '+e.message.slice(0,40)+']'; }
      const vp = log.split('\n').filter(l => /FCWEB-AR|FCWEB-DR|FCWEB-VP|VP-OPEN/.test(l));
      await b.close().catch(()=>{});
      if (vp.length < 2) { console.error('[attempt '+attempt+' got '+vp.length+' markers ('+log.slice(0,40)+'), retrying]'); await new Promise(r=>setTimeout(r,2000)); continue; }
      console.log('=== VP MARKERS (' + vp.length + ') ===');
      console.log(vp.slice(-30).join('\n'));
      return;
    } catch(e) {
      console.error('[attempt '+attempt+' crashed: '+String(e.message).slice(0,60)+']');
      await b.close().catch(()=>{});
      require('child_process').execSync("pkill -9 -f 'Google Chrome' 2>/dev/null || true");
      await new Promise(r=>setTimeout(r,3000));
    }
  }
  console.error('ALL ATTEMPTS FAILED');
})();
