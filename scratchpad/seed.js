// Recreate the failing condition on purpose: a profile carrying many autosaved documents.
const puppeteer = require('puppeteer-core');
const sl = (ms) => new Promise((r) => setTimeout(r, ms));
const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
(async () => {
  const b = await puppeteer.launch({ executablePath: CHROME, headless: false, defaultViewport: null,
    args: ['--no-sandbox', '--use-gl=angle', '--use-angle=metal', '--window-size=1200,800'],
    protocolTimeout: 1200000, userDataDir: '/tmp/fc-returning' });
  const p = (await b.pages())[0];
  await p.goto('http://localhost:8793/index.html', { waitUntil: 'domcontentloaded', timeout: 300000 });
  const t0 = Date.now();
  while (Date.now() - t0 < 300000) { if (await p.evaluate(() => !!(window.fcInstance && window.fcInstance._malloc))) break; await sl(1000); }
  await sl(18000);
  await p.evaluate(() => { const m = window.fcInstance;
    const c = 'import FreeCAD as App\n' +
      'for i in range(12):\n' +
      '    d = App.newDocument("Doc%d" % i)\n' +
      '    d.addObject("Part::Box", "B")\n' +
      '    d.recompute()\n';
    const n = new TextEncoder().encode(c).length + 1; const q = m._malloc(n); m.stringToUTF8(c, q, n);
    (window.fcRunPy || ((mm, pp) => { mm._fcweb_run_python(pp); mm._free(pp); }))(m, q); });
  await sl(12000);
  const n = await p.evaluate(() => { try {
    return window.fcInstance.FS.readdir('/home/web_user/.fcweb-autosave').filter((f) => f.endsWith('.FCStd')).length;
  } catch (e) { return -1; } });
  console.log('seeded autosaves: ' + n);
  await b.close().catch(() => {}); process.exit(0);
})().catch((e) => { console.log('ERR ' + e); process.exit(0); });
