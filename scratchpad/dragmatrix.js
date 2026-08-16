// Which drag actually moves the camera? Real trusted p.mouse events WITH a gap between
// moves (back-to-back moves get coalesced and the camera never moves), on the canvas
// inside Qt's shadow root. Asserts on the camera, never on frames.
const puppeteer = require('puppeteer-core');
const CHROME = process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';  // set CHROME_PATH to run off macOS
const sl = (ms) => new Promise((r) => setTimeout(r, ms));
const run = (p, c) => p.evaluate((c) => { const m = window.fcInstance;
  const n = new TextEncoder().encode(c).length + 1; const q = m._malloc(n); m.stringToUTF8(c, q, n);
  (window.fcRunPy || ((mm, pp) => { mm._fcweb_run_python(pp); mm._free(pp); }))(m, q); }, c);
const waitFor = async (p, mark, ms) => { const t0 = Date.now();
  while (Date.now() - t0 < ms) { const t = await p.evaluate(() => (document.getElementById('log') || {}).textContent || '');
    if (t.includes(mark)) return true; await sl(400); } return false; };
let seq = 0;
const cam = async (p) => { const tag = 'CAM' + (++seq);
  await run(p, 'import FreeCADGui as Gui, sys\nc=Gui.ActiveDocument.ActiveView.getCameraNode()\n' +
    'sys.__stderr__.write("' + tag + ' %s|%s\\n" % (tuple(c.position.getValue()), tuple(c.orientation.getValue().getValue())))\n');
  await waitFor(p, tag, 20000);
  const t = await p.evaluate(() => document.getElementById('log').textContent);
  return ((t.match(new RegExp(tag + ' [^\\n]*')) || [''])[0]).replace(tag + ' ', ''); };
(async () => {
  const b = await puppeteer.launch({ executablePath: CHROME, headless: false, defaultViewport: null,
    args: ['--no-sandbox', '--use-gl=angle', '--use-angle=metal', '--window-size=1400,900'],
    protocolTimeout: 2400000, userDataDir: '/tmp/fc-dragmatrix' });
  const p = (await b.pages())[0];
  await p.goto('http://localhost:8791/index.html', { waitUntil: 'domcontentloaded', timeout: 300000 });
  const t0 = Date.now();
  while (Date.now() - t0 < 300000) { if (await p.evaluate(() => !!(window.fcInstance && window.fcInstance._malloc))) break; await sl(1000); }
  await sl(9000);
  await run(p, ['import FreeCAD as App, FreeCADGui as Gui, sys',
    'd=App.newDocument("T")', 'b=d.addObject("Part::Box","B"); d.recompute()',
    'Gui.activeDocument().activeView().viewIsometric(); Gui.SendMsgToActiveView("ViewFit")',
    'sys.__stderr__.write("READY\\n")'].join('\n'));
  await waitFor(p, 'READY', 120000); await sl(3000);
  const c = await p.evaluate(() => {
    const h = document.getElementById('qt-shadow-container');
    const cv = h && h.shadowRoot && h.shadowRoot.querySelector('canvas');
    const r = (cv || document.body).getBoundingClientRect();
    return { x: Math.round(r.x + r.width * 0.55), y: Math.round(r.y + r.height * 0.5), found: !!cv };
  });
  console.log('canvas point ' + JSON.stringify(c));

  for (const nav of ['Gui::CADNavigationStyle', 'Gui::GestureNavigationStyle']) {
    await run(p, 'import FreeCADGui as Gui\nGui.ActiveDocument.ActiveView.setNavigationType("' + nav + '")');
    await sl(800);
    for (const btn of ['left', 'middle', 'right']) {
      const a = await cam(p);
      await p.mouse.move(c.x, c.y);
      await p.mouse.down({ button: btn });
      for (let i = 1; i <= 15; i++) { await p.mouse.move(c.x + i * 8, c.y + i * 4); await sl(25); }
      await p.mouse.up({ button: btn });
      await sl(1000);
      const z = await cam(p);
      const [pa, oa] = a.split('|'), [pz, oz] = z.split('|');
      const what = pa !== pz && oa !== oz ? 'ROTATED+MOVED' : oa !== oz ? 'ROTATED' : pa !== pz ? 'PANNED' : 'nothing';
      console.log('  ' + nav.replace('Gui::', '').padEnd(24) + btn.padEnd(7) + ' -> ' + what);
    }
  }
  await b.close().catch(() => {}); process.exit(0);
})().catch((e) => { console.log('DRIVER ' + e); process.exit(1); });
