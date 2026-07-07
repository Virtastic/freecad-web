// Full interface + sample-project test for the all-workbenches wave-5 build.
// Boots, lists workbenches, then opens+recomputes each bundled example FCStd
// and reports object counts / a geometry metric. Usage: node wave5-test.js
const puppeteer = require('puppeteer-core');
const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const ARGS = ['--no-sandbox','--disable-dev-shm-usage','--disable-gpu-sandbox',
  '--js-flags=--max-old-space-size=8192','--use-gl=angle','--use-angle=swiftshader',
  '--enable-features=SharedArrayBuffer','--ignore-gpu-blocklist','--window-size=1400,900'];

const PROBE = `
import FreeCADGui as Gui, FreeCAD as App
import os, traceback, sys
def flush(): sys.stdout.flush()
print("PROBE-BEGIN"); flush()
wbs = sorted(Gui.listWorkbenches().keys())
print("WBS n=%d :: %s" % (len(wbs), ",".join(wbs))); flush()
exdir = "/freecad/examples"
try:
    files = sorted(os.listdir(exdir))
except Exception as e:
    files = []
    print("EX-DIR-FAIL %r" % e)
print("EX-FILES %s" % files)
for fn in files:
    if not fn.endswith(".FCStd"): continue
    path = os.path.join(exdir, fn)
    try:
        d = App.openDocument(path)
        try: d.recompute()
        except Exception as re: print("  RECOMPUTE-WARN %s: %r" % (fn, re))
        objs = d.Objects
        nvol = 0; totvol = 0.0
        for o in objs:
            sh = getattr(o, "Shape", None)
            if sh is not None and hasattr(sh, "Volume"):
                try:
                    if sh.Volume > 1e-9: nvol += 1; totvol += sh.Volume
                except Exception: pass
        print("EX-OK %-26s objs=%3d solids=%d totvol=%.1f" % (fn, len(objs), nvol, totvol)); flush()
        App.closeDocument(d.Name)
    except Exception as e:
        print("EX-FAIL %s: %r" % (fn, e)); flush()
        traceback.print_exc(); flush()
print("PROBE-END"); flush()
`;

(async () => {
  const b = await puppeteer.launch({ executablePath: CHROME, headless: 'new', args: ARGS, protocolTimeout: 600000, userDataDir: '/tmp/fc-chrome-profile' });
  try {
    const page = await b.newPage();
    await page.setViewport({ width: 1400, height: 900 });
    const errs = [];
    page.on('pageerror', e => errs.push('[PAGEERROR] ' + String(e.message).slice(0,160)));
    page.on('console', m => { const t=m.text(); if(/abort|RuntimeError|unreachable|Aborted/.test(t)) errs.push('[con] '+t.slice(0,160)); });
    console.log('booting (285MB, allow ~60-90s)...');
    await page.goto('http://localhost:8799/freecad-gui.html', { waitUntil: 'domcontentloaded', timeout: 90000 });
    await page.waitForFunction(() => window.fcInstance && window.fcInstance._malloc, { timeout: 600000, polling: 3000 });
    await new Promise(r => setTimeout(r, 14000));
    console.log('booted; running probe...');
    try {
      await page.evaluate((code) => {
        const m = window.fcInstance;
        const n = new TextEncoder().encode(code).length + 1;
        const p = m._malloc(n); m.stringToUTF8(code, p, n);
        try { m._fcweb_run_python(p); } finally { m._free(p); }
      }, PROBE);
    } catch (e) { console.log('[EVAL-THREW] ' + String(e.message).slice(0,100)); }
    await new Promise(r => setTimeout(r, 8000));
    let log = '';
    try { log = await page.evaluate(() => document.getElementById('log').innerText); }
    catch (e) { log = '[log-read-failed after trap]'; }
    console.log('=== PROBE OUTPUT ===');
    console.log(log.split('\n').filter(l => /PROBE-|WBS|EX-|RECOMPUTE|Traceback|Error/.test(l)).join('\n'));
    if (errs.length) { console.log('=== RUNTIME ERRORS ==='); console.log([...new Set(errs)].slice(-12).join('\n')); }
    else console.log('=== no runtime errors captured ===');
    await page.screenshot({ path: '/tmp/fc-wave5.png' }).catch(()=>{});
  } finally { await b.close().catch(()=>{}); }
})();
