// Is the app installable, and does the service worker leave the 139 MB load alone?
const puppeteer = require('puppeteer-core');
const CHROME = process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';  // set CHROME_PATH to run off macOS
const sl = (ms) => new Promise((r) => setTimeout(r, ms));
(async () => {
  const errs = [];
  const b = await puppeteer.launch({ executablePath: CHROME, headless: false, defaultViewport: null,
    args: ['--no-sandbox', '--use-gl=angle', '--use-angle=metal', '--window-size=1300,850'],
    protocolTimeout: 1800000, userDataDir: '/tmp/fc-installable-' + Date.now() });
  const p = (await b.pages())[0];
  p.on('pageerror', (e) => errs.push(String(e.message || e).slice(0, 140)));
  await p.evaluateOnNewDocument(() => {
    window.__bip = false;
    window.addEventListener('beforeinstallprompt', () => { window.__bip = true; });
  });
  await p.goto(process.argv[2] || 'http://localhost:8792/index.html', { waitUntil: 'domcontentloaded', timeout: 300000 });
  const t0 = Date.now();
  while (Date.now() - t0 < 400000) { if (await p.evaluate(() => !!(window.fcInstance && window.fcInstance._malloc))) break; await sl(1000); }
  const bootMs = Date.now() - t0;
  await sl(14000);
  const st = await p.evaluate(async () => {
    const regs = await navigator.serviceWorker.getRegistrations();
    const mf = document.querySelector('link[rel=manifest]');
    let manifestOk = false, icons = 0;
    try { const r = await fetch(mf.href); const j = await r.json(); manifestOk = !!j.name; icons = j.icons.length; } catch (e) {}
    return {
      swRegistered: regs.length, swState: regs[0] && regs[0].active ? regs[0].active.state : 'none',
      manifestOk, icons, installable: window.__bip || !!window.__fcInstallable,
      booted: !!(window.fcInstance && window.fcInstance._malloc),
      crossOriginIsolated: self.crossOriginIsolated,
    };
  });
  // and the app still works with the worker in place
  await p.evaluate(() => { const m = window.fcInstance;
    const c = 'import FreeCAD as App, sys\nd=App.newDocument("SW")\nb=d.addObject("Part::Box","B")\nd.recompute()\n' +
      'sys.__stderr__.write("SWTEST vol=%.0f\\n" % b.Shape.Volume); sys.__stderr__.flush()\n';
    const n = new TextEncoder().encode(c).length + 1; const q = m._malloc(n); m.stringToUTF8(c, q, n);
    (window.fcRunPy || ((mm, pp) => { mm._fcweb_run_python(pp); mm._free(pp); }))(m, q); });
  await sl(5000);
  const log = await p.evaluate(() => document.getElementById('log').textContent);
  console.log(JSON.stringify(st, null, 1));
  console.log('boot ' + (bootMs / 1000).toFixed(1) + 's, modelling: ' +
    ((log.match(/SWTEST [^\n]*/g) || ['FAILED']).pop()));
  console.log('page errors: ' + (errs.length ? errs.join(' | ') : 'none'));
  await b.close().catch(() => {}); process.exit(0);
})().catch((e) => { console.log('DRIVER ' + String(e).slice(0, 200)); process.exit(0); });
