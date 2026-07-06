// R4 IDBFS persistence test: boot #1 writes a marker file + saves an FCStd into
// $HOME, flushes to IndexedDB, then a SECOND page load (same browser profile /
// same origin IndexedDB) verifies both survived. Usage: node idbfs-test.js
const puppeteer = require('puppeteer-core');
const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const ARGS = ['--no-sandbox','--disable-dev-shm-usage','--disable-gpu-sandbox',
  '--js-flags=--max-old-space-size=8192','--use-gl=angle','--use-angle=swiftshader',
  '--enable-features=SharedArrayBuffer','--ignore-gpu-blocklist','--window-size=1400,900'];

const PY_WRITE = `
import FreeCAD as App, os
home = os.path.expanduser('~')
open(os.path.join(home, '.FreeCAD', 'idbfs-marker.txt'), 'w').write('persist-me-42')
d = App.newDocument('PersistTest')
import Part
b = d.addObject('Part::Box','Box'); b.Length=3; b.Width=4; b.Height=5
d.recompute()
d.saveAs(os.path.join(home, 'PersistTest.FCStd'))
print('IDBFS-WRITE-OK vol=%s' % b.Shape.Volume)
`;

const PY_CHECK = `
import FreeCAD as App, os
home = os.path.expanduser('~')
mk = os.path.join(home, '.FreeCAD', 'idbfs-marker.txt')
fc = os.path.join(home, 'PersistTest.FCStd')
m = open(mk).read() if os.path.exists(mk) else 'MISSING'
if os.path.exists(fc):
    d = App.openDocument(fc)
    d.recompute()
    vol = d.getObject('Box').Shape.Volume
    print('IDBFS-CHECK marker=%s fcstd-vol=%s' % (m, vol))
else:
    print('IDBFS-CHECK marker=%s fcstd=MISSING' % m)
`;

async function boot(page) {
  await page.setViewport({ width: 1400, height: 900 });
  await page.goto('http://localhost:8791/', { waitUntil: 'domcontentloaded', timeout: 60000 });
  await page.waitForFunction(() => window.fcInstance && window.fcInstance._malloc, { timeout: 240000, polling: 3000 });
  await new Promise(r => setTimeout(r, 12000));
}
async function runPy(page, code) {
  await page.evaluate((c) => {
    const m = window.fcInstance;
    const n = new TextEncoder().encode(c).length + 1;
    const p = m._malloc(n); m.stringToUTF8(c, p, n);
    try { m._fcweb_run_python(p); } finally { m._free(p); }
  }, code);
  await new Promise(r => setTimeout(r, 8000));
}
async function flush(page) {
  const r = await page.evaluate(() => new Promise(res => {
    const m = window.fcInstance;
    if (!m || !m.fcwebSyncFS) return res('NO-HOOK');
    m.fcwebSyncFS(e => res(e ? 'ERR:' + e : 'FLUSHED'));
  }));
  console.log('[flush]', r);
  return r;
}
const grep = (log) => log.split('\n').filter(l => /IDBFS-|Error|Traceback/.test(l)).join('\n');

(async () => {
  const b = await puppeteer.launch({ executablePath: CHROME, headless: 'new', args: ARGS, protocolTimeout: 300000 });
  try {
    // --- Boot 1: write + flush ---
    let page = await b.newPage();
    await boot(page);
    await runPy(page, PY_WRITE);
    const f = await flush(page);
    console.log(grep(await page.evaluate(() => document.getElementById('log').innerText)));
    await page.close();
    if (f === 'NO-HOOK') { console.log('FAIL: fcwebSyncFS hook missing (old build?)'); process.exit(1); }

    // --- Boot 2 (fresh page, same origin IndexedDB): verify restore ---
    page = await b.newPage();
    await boot(page);
    await runPy(page, PY_CHECK);
    const log2 = grep(await page.evaluate(() => document.getElementById('log').innerText));
    console.log(log2);
    const ok = /IDBFS-CHECK marker=persist-me-42 fcstd-vol=60\.0/.test(log2);
    console.log(ok ? 'IDBFS-E2E: PASS' : 'IDBFS-E2E: FAIL');
    process.exit(ok ? 0 : 1);
  } finally { await b.close().catch(()=>{}); }
})();
