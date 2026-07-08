// Poll the on-page #log element continuously while FEMExample opens, so the
// [FCWEB-RC] recompute markers are captured right up to the renderer crash.
const fs = require('fs');
const puppeteer = require('puppeteer-core');
const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const ARGS = ['--no-sandbox','--disable-dev-shm-usage','--disable-gpu-sandbox',
  '--js-flags=--max-old-space-size=8192','--use-gl=angle','--use-angle=swiftshader',
  '--enable-features=SharedArrayBuffer','--ignore-gpu-blocklist'];
let PROFILE = '/tmp/fc-chrome-profile';
try { PROFILE = '/tmp/fc-chrome-profile-' + Math.floor(fs.statSync('/Users/mstavridis/Downloads/FreeCAD-Web/play-gui/FreeCAD.wasm').mtimeMs); } catch(e){}
const PY = `
import sys
import FreeCAD as App
print("VP-OPEN-BEGIN"); sys.stdout.flush()
d = App.openDocument("/freecad/examples/FEMExample.FCStd")
print("VP-OPEN-DONE objs=%d" % len(d.Objects)); sys.stdout.flush()
`;
(async () => {
  for (let attempt = 1; attempt <= 4; attempt++) {
    const b = await puppeteer.launch({ executablePath: CHROME, headless:'new', args:ARGS, protocolTimeout:600000, userDataDir: PROFILE });
    let lastGood = '';
    try {
      const page = await b.newPage();
      await page.goto('http://localhost:8799/freecad-gui.html', { waitUntil:'domcontentloaded', timeout:120000 });
      await page.waitForFunction(() => window.fcInstance && window.fcInstance._malloc, { timeout: 540000, polling: 2500 });
      await new Promise(r=>setTimeout(r,12000));
      // fire the eval WITHOUT awaiting (it will trap); poll the log meanwhile
      page.evaluate((code) => {
        const m = window.fcInstance;
        const n = new TextEncoder().encode(code).length + 1;
        const p = m._malloc(n); m.stringToUTF8(code, p, n);
        try { m._fcweb_run_python(p); } catch(e){} finally { try{m._free(p);}catch(_){} }
      }, PY).catch(()=>{});
      // poll for up to 40s or until the tab dies
      for (let i = 0; i < 100; i++) {
        await new Promise(r=>setTimeout(r,400));
        let cur;
        try { cur = await page.evaluate(() => document.getElementById('log').innerText); }
        catch(e){ break; } // tab crashed
        if (cur && cur.length) lastGood = cur;
        if (/VP-OPEN-DONE/.test(cur)) break; // finished without trap
      }
    } catch(e) { /* boot crash */ }
    await b.close().catch(()=>{});
    const marks = lastGood.split('\n').filter(l => /FCWEB-FR|FCWEB-RC|VP-OPEN/.test(l));
    if (marks.length) {
      console.log('=== attempt '+attempt+': last 22 recompute markers ('+marks.length+' total) ===');
      console.log(marks.slice(-22).join('\n'));
      return;
    }
    console.error('[attempt '+attempt+' got no markers, retrying]');
    require('child_process').execSync("pkill -9 -f 'Google Chrome' 2>/dev/null || true");
    await new Promise(r=>setTimeout(r,3000));
  }
  console.error('ALL ATTEMPTS: no markers');
})();
