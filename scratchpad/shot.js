// Open an example in the 3D viewport and screenshot it. arg1=example filename.
const puppeteer = require('puppeteer-core');
const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const ARGS = ['--no-sandbox','--disable-dev-shm-usage','--disable-gpu-sandbox',
  '--js-flags=--max-old-space-size=8192','--use-gl=angle','--use-angle=swiftshader',
  '--enable-features=SharedArrayBuffer','--ignore-gpu-blocklist','--window-size=1400,900'];
const FN = process.argv[2] || 'EngineBlock.FCStd';
(async () => {
  const b = await puppeteer.launch({ executablePath: CHROME, headless:'new', args: ARGS, protocolTimeout: 500000, userDataDir:'/tmp/fc-chrome-profile' });
  const page = await b.newPage();
  await page.setViewport({ width: 1400, height: 900 });
  await page.goto('http://localhost:8792/freecad-gui.html?render3d=1', { waitUntil:'domcontentloaded', timeout:120000 });
  await page.waitForFunction(() => window.fcInstance && window.fcInstance._malloc, { timeout: 480000, polling: 2000 });
  await new Promise(r => setTimeout(r, 12000));
  const PY = `
import FreeCAD as App, FreeCADGui as Gui
d = App.openDocument("/freecad/examples/${FN}")
d.recompute()
Gui.activeDocument().activeView().viewIsometric()
Gui.SendMsgToActiveView("ViewFit")
print("SHOT-OPENED ${FN} objs=%d" % len(d.Objects))
`;
  try {
    await page.evaluate((code) => {
      const m = window.fcInstance;
      const n = new TextEncoder().encode(code).length + 1;
      const p = m._malloc(n); m.stringToUTF8(code, p, n);
      try { m._fcweb_run_python(p); } finally { m._free(p); }
    }, PY);
  } catch (e) { console.log('[eval] '+String(e.message).slice(0,80)); }
  // let the overlay compositor blit a few frames
  await new Promise(r => setTimeout(r, 12000));
  const out = '/tmp/fc-3d-' + FN.replace(/\W+/g,'_') + '.png';
  await page.screenshot({ path: out });
  const log = await page.evaluate(() => document.getElementById('log').innerText).catch(()=> '');
  console.log(log.split('\n').filter(l=>/SHOT-|Error/.test(l)).slice(-4).join('\n'));
  console.log('SCREENSHOT ' + out);
  await b.close().catch(()=>{});
})();
