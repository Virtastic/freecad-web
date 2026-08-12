// End-to-end FEM in the real browser: box -> gmsh mesh -> CalculiX solve -> results.
//
// Reads the Python from /tmp/ccxe2e.py, waits for the app to boot, runs it, then polls
// the on-page log for the CX- markers the script prints. Dumps the log tail either way,
// because a silent failure is the thing most worth seeing.
const puppeteer = require('puppeteer-core');
const fs = require('fs');
const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const sl = (ms) => new Promise((r) => setTimeout(r, ms));
const CODE = fs.readFileSync('/tmp/ccxe2e.py', 'utf8');

(async () => {
  const errs = [];
  const b = await puppeteer.launch({
    executablePath: CHROME, headless: false,   // a real GL context: headless angle/metal breaks Coin's GL hooks
    defaultViewport: null,
    args: ['--no-sandbox', '--use-gl=angle', '--use-angle=metal',
           '--enable-features=SharedArrayBuffer', '--window-size=1400,900'],
    protocolTimeout: 2400000, userDataDir: '/tmp/fc-prod',
  });
  const p = (await b.pages())[0];
  p.on('pageerror', (e) => errs.push('PAGEERR ' + String(e).slice(0, 160)));
  p.on('console', (m) => { const t = m.text(); if (/fcweb|ccx|error/i.test(t)) errs.push('CON ' + t.slice(0, 160)); });

  await p.goto('https://freecad.virtastic.app/', { waitUntil: 'domcontentloaded', timeout: 300000 });
  const t0 = Date.now(); let ready = false;
  while (Date.now() - t0 < 300000) {
    if (await p.evaluate(() => !!(window.fcInstance && window.fcInstance._malloc))) { ready = true; break; }
    await sl(500);
  }
  await sl(10000);

  const bridges = await p.evaluate(() => ({
    ccx: typeof window.fcwebCcxRun, gmsh: typeof window.fcwebGmshRun,
  }));

  await p.evaluate((code) => {
    const m = window.fcInstance;
    const n = new TextEncoder().encode(code).length + 1;
    const q = m._malloc(n);
    m.stringToUTF8(code, q, n);
    (window.fcRunPy || ((mm, pp) => { mm._fcweb_run_python(pp); mm._free(pp); }))(m, q);
  }, CODE);

  const t1 = Date.now(); let done = false;
  while (Date.now() - t1 < 1800000) {
    const txt = await p.evaluate(() => {
      const e = document.getElementById('log');
      return e ? e.textContent : '';
    });
    if (txt.includes('CX-END')) { done = true; break; }
    await sl(3000);
  }
  await sl(2000);

  const log = await p.evaluate(() => {
    const e = document.getElementById('log');
    return e ? e.textContent : '(no log element)';
  });
  const marks = log.split('\n').filter((l) => l.includes('CX-'));
  const out = [
    'ready=' + ready, 'bridges=' + JSON.stringify(bridges), 'reachedEnd=' + done,
    '--- markers ---', marks.join('\n') || '(none)',
    '--- log tail ---', log.slice(-2200),
    '--- errors (' + errs.length + ') ---', errs.slice(0, 8).join('\n'),
  ].join('\n');
  fs.writeFileSync('/tmp/ccxprod.txt', out);
  console.log(out);
  await b.close().catch(() => {});
  process.exit(0);
})().catch((e) => {
  const m = 'DRIVER-ERR ' + String(e).slice(0, 300);
  fs.writeFileSync('/tmp/ccxprod.txt', m); console.log(m); process.exit(0);
});
