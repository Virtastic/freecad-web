// Settings survive a reload (GitHub #2: "the settings are not persisted, on reload all
// settings of the 3D mouse are lost"). Sets a Spaceball Motion preference the way its
// dialog does (a parameter write, no explicit save), hides the tab the way a reload does,
// then reloads in the same profile and reads it back.
//   node scratchpad/prefpersist.js [url]
const puppeteer = require('puppeteer-core');
const sl = (ms) => new Promise((r) => setTimeout(r, ms));
const NL = String.fromCharCode(10);
const URL = process.argv[2] || 'http://127.0.0.1:8792/freecad-gui.html';
const PROFILE = 'C:/Users/MICHAE~1/AppData/Local/Temp/fc-pp-' + Date.now();
const runPy = (p, c) => p.evaluate((c) => { const m = window.fcInstance; const n = new TextEncoder().encode(c).length + 1; const q = m._malloc(n); m.stringToUTF8(c, q, n); window.fcRunPy(m, q); }, c);
const G = 'App.ParamGet("User parameter:Spaceball/Motion")';
const once = async (code) => {
  const b = await puppeteer.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: true, args: ['--no-sandbox', '--use-gl=angle'], defaultViewport: { width: 1400, height: 900 }, protocolTimeout: 900000, userDataDir: PROFILE });
  const p = (await b.pages())[0];
  await p.goto(URL, { waitUntil: 'domcontentloaded', timeout: 300000 });
  const t = Date.now();
  while (Date.now() - t < 420000) { if (await p.evaluate(() => !!window.__fcWorkReady && !!(window.fcInstance && window.fcInstance._malloc))) break; await sl(1500); }
  await sl(10000);
  let r = null;
  for (let i = 0; i < 6 && !r; i++) {
    await runPy(p, ['import FreeCAD as App', code, 'open("/tmp/pp.txt","w").write(str(' + G + '.GetInt("GlobalSensitivity", -99)))'].join(NL));
    await sl(2500);
    r = await p.evaluate(() => { try { return window.fcInstance.FS.readFile('/tmp/pp.txt', { encoding: 'utf8' }); } catch (e) { return null; } });
  }
  // what a reload does to the page first
  await p.evaluate(() => { Object.defineProperty(document, 'hidden', { configurable: true, get: () => true }); document.dispatchEvent(new Event('visibilitychange')); });
  await sl(8000);   // the save, then the IDBFS sync
  await b.close();
  return r;
};
(async () => {
  const a = await once(G + '.SetInt("GlobalSensitivity", 17)');
  const b = await once('');
  console.log('  set: ' + a + '   after reload: ' + b);
  const pass = a === '17' && b === '17';
  console.log(pass ? 'all passed: Spaceball settings survive a reload' : 'FAILED');
  process.exit(pass ? 0 : 1);
})();
