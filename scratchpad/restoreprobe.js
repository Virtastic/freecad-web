// After a reload: is the recovery file present in the FS, when does it appear, and does
// the restore pass actually open it?
const puppeteer = require('puppeteer-core');
const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const sl = (ms) => new Promise((r) => setTimeout(r, ms));
const PROFILE = '/tmp/fc-restoreprobe';
const run = (p, c) => p.evaluate((c) => { const m = window.fcInstance;
  const n = new TextEncoder().encode(c).length + 1; const q = m._malloc(n); m.stringToUTF8(c, q, n);
  (window.fcRunPy || ((mm, pp) => { mm._fcweb_run_python(pp); mm._free(pp); }))(m, q); }, c);
async function waitReady(p) {
  const t0 = Date.now();
  while (Date.now() - t0 < 300000) { if (await p.evaluate(() => !!(window.fcInstance && window.fcInstance._malloc))) break; await sl(500); }
}
(async () => {
  const fresh = process.argv[2] === 'fresh';
  const b = await puppeteer.launch({ executablePath: CHROME, headless: false, defaultViewport: null,
    args: ['--no-sandbox', '--use-gl=angle', '--use-angle=metal', '--window-size=1200,800'],
    protocolTimeout: 1200000, userDataDir: PROFILE + (fresh ? '-' + Date.now() : '') });
  const p = (await b.pages())[0];

  // ---- session 1: model something, wait for the save, reload
  await p.goto('http://localhost:8791/index.html', { waitUntil: 'domcontentloaded', timeout: 300000 });
  await waitReady(p); await sl(18000);
  await run(p, 'import FreeCAD as App, sys\nd=App.newDocument("RDoc")\n' +
    'b=d.addObject("Part::Box","B"); b.Length=42\nd.recompute()\n' +
    'sys.__stderr__.write("MADE\\n"); sys.__stderr__.flush()\n');
  await sl(4000);
  const before = await p.evaluate(() => {
    const m = window.fcInstance; let f = [];
    try { f = m.FS.readdir('/home/web_user/.fcweb-autosave').filter((x) => x !== '.' && x !== '..'); } catch (e) { f = ['<no dir>']; }
    return f;
  });
  console.log('session1 recovery dir before reload:', JSON.stringify(before));

  // ---- session 2: reload and watch
  await p.goto('http://localhost:8791/index.html', { waitUntil: 'domcontentloaded', timeout: 300000 });
  await waitReady(p);
  for (const t of [3, 8, 14, 20, 26]) {
    await sl(t === 3 ? 3000 : (t === 8 ? 5000 : 6000));
    const st = await p.evaluate(() => {
      const m = window.fcInstance; let f = [];
      try { f = m.FS.readdir('/home/web_user/.fcweb-autosave').filter((x) => x !== '.' && x !== '..'); } catch (e) { f = ['<no dir>']; }
      const log = document.getElementById('log').textContent;
      return { f, restored: (log.match(/restored \d+ recovered[^\n]*/) || ['-'])[0] };
    });
    console.log('  t=+' + t + 's  recoveryDir=' + JSON.stringify(st.f) + '  log=' + st.restored);
  }
  await run(p, 'import FreeCAD as App, sys\n' +
    'sys.__stderr__.write("DOCS %s\\n" % ",".join(sorted(App.listDocuments().keys())) )\nsys.__stderr__.flush()\n');
  await sl(2500);
  const log = await p.evaluate(() => document.getElementById('log').textContent);
  console.log('  ' + ((log.match(/DOCS [^\n]*/g) || ['DOCS (none)']).pop()));
  await b.close().catch(() => {}); process.exit(0);
})().catch((e) => { console.log('DRIVER ' + String(e).slice(0, 200)); process.exit(0); });
