// Boot the build, then run a Python probe via the JS bridge to confirm the new
// C++ workbenches import, register workbenches, and do real geometry.
const puppeteer = require('puppeteer-core');
const CHROME = process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';  // set CHROME_PATH to run off macOS

const PY = `
import FreeCAD as App
res = {}
for m in ['Mesh','Points','Surface','Measure','Import','Inspection']:
    try:
        __import__(m); res[m]='import-OK'
    except Exception as e:
        res[m]='IMPORT-FAIL: %r'%e
import FreeCADGui as Gui
wbs = list(Gui.listWorkbenches().keys())
for w in ['MeshWorkbench','PointsWorkbench','SurfaceWorkbench','MeasureWorkbench','ImportWorkbench','InspectionWorkbench']:
    res[w] = ('WB-OK' if w in wbs else 'WB-MISSING')
# real Mesh geometry: build a cube mesh
try:
    import Mesh
    d = App.newDocument('MeshTest')
    m = Mesh.createBox(10,10,10)
    obj = d.addObject('Mesh::Feature','Cube'); obj.Mesh = m; d.recompute()
    res['MeshGeom'] = 'pts=%d facets=%d' % (m.CountPoints, m.CountFacets)
except Exception as e:
    res['MeshGeom'] = 'MESH-FAIL: %r'%e
print('WAVE1-PROBE ' + repr(res))
print('WAVE1-DONE')
`;

(async () => {
  const browser = await puppeteer.launch({
    executablePath: CHROME, headless: 'new',
    args: ['--no-sandbox','--disable-dev-shm-usage','--disable-gpu-sandbox','--js-flags=--max-old-space-size=8192','--use-gl=angle','--use-angle=swiftshader',
           '--enable-features=SharedArrayBuffer','--ignore-gpu-blocklist','--window-size=1400,900'],
  });
  const page = await browser.newPage();
  await page.setViewport({ width: 1400, height: 900 });
  const lines = [];
  page.on('console', m => lines.push('[c] ' + m.text()));
  page.on('pageerror', e => lines.push('[PAGEERROR] ' + e.message));
  await page.goto('http://localhost:8791/freecad-gui.html', { waitUntil: 'domcontentloaded', timeout: 60000 });

  // wait for boot + pyside warmup (warmup runs at 8s)
  await new Promise(r => setTimeout(r, 30000));
  // run the probe via the bridge
  await page.evaluate((code) => {
    const m = window.fcInstance;
    const n = new TextEncoder().encode(code).length + 1;
    const p = m._malloc(n); m.stringToUTF8(code, p, n);
    try { m._fcweb_run_python(p); } finally { m._free(p); }
  }, PY);
  await new Promise(r => setTimeout(r, 6000));

  const log = await page.evaluate(() => document.getElementById('log').innerText);
  await page.screenshot({ path: '/tmp/fc-wave1.png' });
  const probe = log.split('\n').filter(l => /WAVE1|FAIL|MISSING|Traceback|Error/.test(l));
  console.log('=== PROBE LINES ===\n' + probe.join('\n'));
  console.log('=== CONSOLE probe/err ===\n' + lines.filter(l=>/WAVE1|FAIL|MISSING|Error|PAGEERROR/.test(l)).slice(-30).join('\n'));
  await browser.close();
})().catch(e => { console.error('ERR', e); process.exit(1); });
