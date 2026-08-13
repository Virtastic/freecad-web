// What is that profile actually running, and what is it doing?
const puppeteer = require('puppeteer-core');
const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const sl = (ms) => new Promise((r) => setTimeout(r, ms));
(async () => {
  const b = await puppeteer.launch({ executablePath: CHROME, headless: false, defaultViewport: null,
    args: ['--no-sandbox', '--use-gl=angle', '--use-angle=metal', '--window-size=1300,850'],
    protocolTimeout: 1800000, userDataDir: '/tmp/fc-regression' });
  const p = (await b.pages())[0];
  const reqs = [];
  p.on('response', (r) => { const u = r.url();
    if (/freecad\.virtastic\.app\/($|freecad-gui|FreeCAD\.data)/.test(u))
      reqs.push(r.status() + ' ' + (r.fromCache() ? 'FROM-CACHE ' : 'network ') + u.split('/').pop().slice(0, 40)); });
  await p.goto('https://freecad.virtastic.app/', { waitUntil: 'domcontentloaded', timeout: 300000 });
  const t0 = Date.now();
  while (Date.now() - t0 < 300000) { if (await p.evaluate(() => !!(window.fcInstance && window.fcInstance._malloc))) break; await sl(1000); }
  console.log('requests: ' + JSON.stringify(reqs));
  console.log('page has the restore cap: ' + await p.evaluate(() =>
    document.documentElement.innerHTML.includes('older recovery file')));
  for (const t of [8, 20, 40]) {
    await sl(t === 8 ? 8000 : 12000 + (t > 30 ? 8000 : 0));
    const st = await p.evaluate(() => {
      const m = window.fcInstance; let files = [];
      try { files = m.FS.readdir('/home/web_user/.fcweb-autosave').filter((f) => f.endsWith('.FCStd')); } catch (e) {}
      const log = document.getElementById('log').textContent;
      const spam = (log.match(/readobject called with exception set/g) || []).length;
      return { autosaves: files.length, busy: !!window.__fcPyBusy,
               restored: (log.match(/restored \d+ document[^\n]*/) || ['-'])[0],
               older: (log.match(/older recovery file[^\n]*/) || ['-'])[0],
               readobjectSpam: spam, tail: log.slice(-120).replace(/\s+/g, ' ') };
    });
    console.log('t=+' + t + 's ' + JSON.stringify(st));
  }
  // is the interpreter responsive at all?
  await p.evaluate(() => { const m = window.fcInstance;
    const c = 'import sys\nsys.__stderr__.write("PING ok\\n"); sys.__stderr__.flush()\n';
    const n = new TextEncoder().encode(c).length + 1; const q = m._malloc(n); m.stringToUTF8(c, q, n);
    (window.fcRunPy || ((mm, pp) => { mm._fcweb_run_python(pp); mm._free(pp); }))(m, q); });
  await sl(8000);
  console.log('interpreter responds: ' + await p.evaluate(() =>
    document.getElementById('log').textContent.includes('PING ok')));
  await b.close().catch(() => {}); process.exit(0);
})().catch((e) => { console.log('DRIVER ' + String(e).slice(0, 250)); process.exit(0); });
