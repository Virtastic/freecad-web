// Chrome's sampling profiler across a real drag orbit. Aggregates self-time by function
// so the answer comes from measurement, not from reading the render path and guessing.
const puppeteer = require('puppeteer-core');
const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const sl = (ms) => new Promise((r) => setTimeout(r, ms));
const run = (p, c) => p.evaluate((c) => { const m = window.fcInstance;
  const n = new TextEncoder().encode(c).length + 1; const q = m._malloc(n); m.stringToUTF8(c, q, n);
  (window.fcRunPy || ((mm, pp) => { mm._fcweb_run_python(pp); mm._free(pp); }))(m, q); }, c);
const waitFor = async (p, mark, ms) => { const t0 = Date.now();
  while (Date.now() - t0 < ms) { const t = await p.evaluate(() => (document.getElementById('log') || {}).textContent || '');
    if (t.includes(mark)) return true; await sl(500); } return false; };
const MODEL = process.argv[2] || 'EngineBlock';
(async () => {
  const b = await puppeteer.launch({ executablePath: CHROME, headless: false, defaultViewport: null,
    args: ['--no-sandbox', '--use-gl=angle', '--use-angle=metal', '--window-size=1400,900'],
    protocolTimeout: 2400000, userDataDir: '/tmp/fc-cpuprof' });
  const p = (await b.pages())[0];
  await p.goto('http://localhost:8791/index.html', { waitUntil: 'domcontentloaded', timeout: 300000 });
  const t0 = Date.now();
  while (Date.now() - t0 < 300000) { if (await p.evaluate(() => !!(window.fcInstance && window.fcInstance._malloc))) break; await sl(1000); }
  await sl(9000);
  await run(p, ['import sys, FreeCAD as App, FreeCADGui as Gui',
    'd=App.openDocument("/freecad/share/examples/' + MODEL + '.FCStd")', 'Gui.updateGui()',
    'av=Gui.ActiveDocument.ActiveView', 'av.viewAxonometric(); av.fitAll(); Gui.updateGui()',
    'sys.__stderr__.write("VP-OPEN\\n"); sys.__stderr__.flush()'].join('\n'));
  await waitFor(p, 'VP-OPEN', 900000); await sl(3000);

  const cdp = await p.target().createCDPSession();
  await cdp.send('Profiler.enable');
  await cdp.send('Profiler.setSamplingInterval', { interval: 200 });   // 0.2 ms
  await cdp.send('Profiler.start');
  await p.mouse.move(700, 450); await p.mouse.down({ button: 'left' });
  for (let i = 0; i < 60; i++) { await p.mouse.move(700 + Math.round(150 * Math.sin(i / 7)), 450 + Math.round(100 * Math.cos(i / 6))); }
  await p.mouse.up({ button: 'left' });
  const { profile } = await cdp.send('Profiler.stop');

  const byId = new Map(profile.nodes.map((n) => [n.id, n]));
  const self = new Map();
  for (let i = 0; i < profile.samples.length; i++) {
    const n = byId.get(profile.samples[i]);
    if (!n) continue;
    const f = n.callFrame;
    const key = (f.functionName || '(anonymous)') + '  @' + (f.url || '').split('/').pop() + ':' + f.lineNumber;
    const dt = profile.timeDeltas[i] || 0;
    self.set(key, (self.get(key) || 0) + dt);
  }
  const total = [...self.values()].reduce((a, c) => a + c, 0);
  const top = [...self.entries()].sort((a, b) => b[1] - a[1]).slice(0, 18);
  console.log(MODEL + '  total sampled: ' + Math.round(total / 1000) + ' ms');
  for (const [k, us] of top) {
    console.log('  ' + String(Math.round(us / 1000)).padStart(5) + ' ms  ' +
                String(Math.round(1000 * us / total) / 10).padStart(5) + '%  ' + k);
  }
  await b.close().catch(() => {}); process.exit(0);
})().catch((e) => { console.log('DRIVER ' + e); process.exit(1); });
