// Production smoke test: boots, storage is persistent, crash reporter present, FEM path
// alive. Run after every deploy that touches the loader or the data URL.
const puppeteer = require('puppeteer-core');
const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const sl = (ms) => new Promise((r) => setTimeout(r, ms));
(async () => {
  const errs = [];
  const b = await puppeteer.launch({ executablePath: CHROME, headless: false, defaultViewport: null,
    args: ['--no-sandbox', '--use-gl=angle', '--use-angle=metal', '--window-size=1300,850'],
    protocolTimeout: 1800000, userDataDir: '/tmp/fc-prodcheck-' + Date.now() });
  const p = (await b.pages())[0];
  p.on('pageerror', (e) => errs.push('PAGEERR ' + String(e.message || e).slice(0, 160)));
  const data = [];
  p.on('response', (r) => { if (/FreeCAD\.data/.test(r.url())) data.push(r.url().split('/').pop() + ' ' + r.status()); });
  const t0 = Date.now();
  await p.goto('https://freecad.virtastic.app/', { waitUntil: 'domcontentloaded', timeout: 300000 });
  let ready = false;
  while (Date.now() - t0 < 420000) { if (await p.evaluate(() => !!(window.fcInstance && window.fcInstance._malloc))) { ready = true; break; } await sl(1000); }
  const bootMs = Date.now() - t0;
  await sl(14000);
  const st = await p.evaluate(async () => ({
    persisted: navigator.storage && navigator.storage.persisted ? await navigator.storage.persisted() : 'n/a',
    crashReporter: typeof window.fcwebCrash,
    notify: typeof window.fcwebNotify,
    ccx: typeof window.fcwebCcxRun, gmsh: typeof window.fcwebGmshRun,
    est: navigator.storage && navigator.storage.estimate ? await navigator.storage.estimate().then(
      (q) => Math.round(q.usage / 1048576) + 'MB / ' + Math.round(q.quota / 1048576) + 'MB') : 'n/a',
  }));
  await p.evaluate(() => { const m = window.fcInstance;
    const c = 'import FreeCAD as App, sys\nd=App.newDocument("P")\nb=d.addObject("Part::Box","B")\nd.recompute()\n' +
      'sys.__stderr__.write("PROD vol=%.0f\\n" % b.Shape.Volume); sys.__stderr__.flush()\n';
    const n = new TextEncoder().encode(c).length + 1; const q = m._malloc(n); m.stringToUTF8(c, q, n);
    (window.fcRunPy || ((mm, pp) => { mm._fcweb_run_python(pp); mm._free(pp); }))(m, q); });
  await sl(6000);
  const log = await p.evaluate(() => document.getElementById('log').textContent);
  console.log('booted=' + ready + ' in ' + (bootMs / 1000).toFixed(1) + 's');
  console.log('data requests: ' + JSON.stringify([...new Set(data)]));
  console.log('state: ' + JSON.stringify(st));
  console.log('modelling: ' + ((log.match(/PROD [^\n]*/g) || ['FAILED']).pop()));
  console.log('page errors: ' + (errs.length ? errs.join(' | ') : 'none'));
  await b.close().catch(() => {}); process.exit(0);
})().catch((e) => { console.log('DRIVER ' + String(e).slice(0, 200)); process.exit(1); });
