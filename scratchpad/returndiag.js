// A returning user's profile wedges where a fresh one does not. Two candidates: the
// service worker now controlling the page, or the autosave restore reopening every
// document from every previous session. Look at both before touching anything.
const puppeteer = require('puppeteer-core');
const CHROME = process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';  // set CHROME_PATH to run off macOS
const sl = (ms) => new Promise((r) => setTimeout(r, ms));
const run = (p, c) => p.evaluate((c) => { const m = window.fcInstance;
  const n = new TextEncoder().encode(c).length + 1; const q = m._malloc(n); m.stringToUTF8(c, q, n);
  (window.fcRunPy || ((mm, pp) => { mm._fcweb_run_python(pp); mm._free(pp); }))(m, q); }, c);
(async () => {
  const b = await puppeteer.launch({ executablePath: CHROME, headless: false, defaultViewport: null,
    args: ['--no-sandbox', '--use-gl=angle', '--use-angle=metal', '--window-size=1300,850'],
    protocolTimeout: 1800000, userDataDir: '/tmp/fc-regression' });   // the profile that fails
  const p = (await b.pages())[0];
  await p.goto('https://freecad.virtastic.app/', { waitUntil: 'domcontentloaded', timeout: 300000 });
  const t0 = Date.now();
  while (Date.now() - t0 < 300000) { if (await p.evaluate(() => !!(window.fcInstance && window.fcInstance._malloc))) break; await sl(1000); }
  console.log('instance ready after ' + ((Date.now() - t0) / 1000).toFixed(1) + 's');
  const sw = await p.evaluate(async () => {
    const regs = await navigator.serviceWorker.getRegistrations();
    return { count: regs.length, controlled: !!navigator.serviceWorker.controller };
  });
  console.log('service worker: ' + JSON.stringify(sw));
  for (const t of [5, 15, 30, 50]) {
    await sl(t === 5 ? 5000 : 10000 + (t > 20 ? 10000 : 0));
    const st = await p.evaluate(() => {
      const m = window.fcInstance;
      let files = [];
      try { files = m.FS.readdir('/home/web_user/.fcweb-autosave').filter((f) => f.endsWith('.FCStd')); } catch (e) {}
      const log = document.getElementById('log').textContent;
      return { autosaves: files.length, names: files.slice(0, 8),
        busy: !!window.__fcPyBusy,
        restored: (log.match(/restored \d+ document/) || ['-'])[0],
        logTail: log.slice(-160).replace(/\s+/g, ' ') };
    });
    console.log('t=+' + t + 's ' + JSON.stringify(st));
  }
  await b.close().catch(() => {}); process.exit(0);
})().catch((e) => { console.log('DRIVER ' + String(e).slice(0, 250)); process.exit(0); });
