// Returning visitors: the page used to force Gesture navigation on everyone (issue #6).
// Boot the OLD page once in a profile, then the new one in the SAME profile, and read the
// navigation style each time: new page -> CAD, desktop's default. Then pick Gesture on
// purpose and reboot: the choice must survive.
//   node scratchpad/navmigrate.js [base url]   (old page served as old.html beside it)
const puppeteer = require('puppeteer-core');
const sl = (ms) => new Promise((r) => setTimeout(r, ms));
const NL = String.fromCharCode(10);
const BASE = process.argv[2] || 'http://127.0.0.1:8792/';
const PROFILE = 'C:/Users/MICHAE~1/AppData/Local/Temp/fc-navmig-' + Date.now();
let fails = 0;
const ok = (c, m) => { console.log((c ? '  ok   ' : '  FAIL ') + m); if (!c) fails++; };
const boot = async (page, code) => {
  const b = await puppeteer.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: true, args: ['--no-sandbox', '--use-gl=angle'], defaultViewport: { width: 1400, height: 900 }, protocolTimeout: 900000, userDataDir: PROFILE });
  const p = (await b.pages())[0];
  await p.goto(BASE + page, { waitUntil: 'domcontentloaded', timeout: 300000 });
  const t = Date.now();
  while (Date.now() - t < 420000) { if (await p.evaluate(() => !!window.__fcWorkReady && !!(window.fcInstance && window.fcInstance._malloc))) break; await sl(1500); }
  await sl(10000);
  let r = null;
  for (let i = 0; i < 6 && !r; i++) {
    await p.evaluate((c) => { const m = window.fcInstance, n = new TextEncoder().encode(c).length + 1, q = m._malloc(n); m.stringToUTF8(c, q, n); window.fcRunPy(m, q); },
      ['import FreeCAD as App', 'g = App.ParamGet("User parameter:BaseApp/Preferences/View")', code || '', 'open("/tmp/nav.txt","w").write(g.GetString("NavigationStyle"))'].join(NL));
    await sl(2500);
    r = await p.evaluate(() => { try { return window.fcInstance.FS.readFile('/tmp/nav.txt', { encoding: 'utf8' }); } catch (e) { return null; } });
  }
  await sl(6000);   // let the IDBFS home sync before closing
  await b.close();
  return r;
};
(async () => {
  const a = await boot('old.html');
  ok(/Gesture/.test(a || ''), 'the old page left this visitor on Gesture: ' + a);
  const b2 = await boot('freecad-gui.html');
  ok(/CADNavigation/.test(b2 || ''), 'the new page puts them back on desktop\'s default: ' + b2);
  await boot('freecad-gui.html', 'g.SetString("NavigationStyle", "Gui::GestureNavigationStyle"); App.saveParameter()');
  const d = await boot('freecad-gui.html');
  ok(/Gesture/.test(d || ''), 'a style they pick afterwards is kept: ' + d);
  console.log(fails ? fails + ' FAILED' : 'all passed');
  process.exit(fails ? 1 : 0);
})();
