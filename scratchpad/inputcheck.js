const puppeteer = require('puppeteer-core');
const CHROME = process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';  // set CHROME_PATH to run off macOS
const sl = (ms) => new Promise((r) => setTimeout(r, ms));
const run = (p, c) => p.evaluate((c) => { const m = window.fcInstance;
  const n = new TextEncoder().encode(c).length + 1; const q = m._malloc(n); m.stringToUTF8(c, q, n);
  (window.fcRunPy || ((mm, pp) => { mm._fcweb_run_python(pp); mm._free(pp); }))(m, q); }, c);
const waitFor = async (p, mark, ms) => { const t0 = Date.now();
  while (Date.now() - t0 < ms) { const t = await p.evaluate(() => (document.getElementById('log') || {}).textContent || '');
    if (t.includes(mark)) return true; await sl(500); } return false; };
const tail = async (p, re) => { const t = await p.evaluate(() => document.getElementById('log').textContent);
  const m = t.match(re) || []; return m[m.length - 1] || '(none)'; };
(async () => {
  const b = await puppeteer.launch({ executablePath: CHROME, headless: false, defaultViewport: null,
    args: ['--no-sandbox', '--use-gl=angle', '--use-angle=metal', '--window-size=1400,900'],
    protocolTimeout: 2400000, userDataDir: '/tmp/fc-inputcheck' });
  const p = (await b.pages())[0];
  const cdp = await p.target().createCDPSession();
  await p.goto('http://localhost:8791/index.html', { waitUntil: 'domcontentloaded', timeout: 300000 });
  const t0 = Date.now();
  while (Date.now() - t0 < 300000) { if (await p.evaluate(() => !!(window.fcInstance && window.fcInstance._malloc))) break; await sl(1000); }
  await sl(9000);
  await run(p, ['import sys, FreeCAD as App, FreeCADGui as Gui',
    'd=App.openDocument("/freecad/share/examples/EngineBlock.FCStd")', 'Gui.updateGui()',
    'av=Gui.ActiveDocument.ActiveView', 'av.viewAxonometric(); av.fitAll(); Gui.updateGui()',
    'sys.__stderr__.write("OPEN\\n"); sys.__stderr__.flush()'].join('\n'));
  await waitFor(p, 'OPEN', 900000); await sl(2500);

  const report = async (tag) => { await run(p,
    'import FreeCADGui as Gui, sys\nav=Gui.ActiveDocument.ActiveView\nc=av.getCameraNode()\n' +
    'sys.__stderr__.write("' + tag + ' pos=%s h=%s sel=%d\\n" % (tuple(c.position.getValue()), ' +
    'getattr(c,"height",None) and c.height.getValue(), len(Gui.Selection.getSelection())))\n');
    await sl(800); return await tail(p, new RegExp(tag + ' [^\\n]*', 'g')); };

  console.log('start   ' + await report('S'));
  // click on the model
  await cdp.send('Input.dispatchMouseEvent', { type: 'mousePressed', x: 700, y: 420, button: 'left', buttons: 1, clickCount: 1 });
  await cdp.send('Input.dispatchMouseEvent', { type: 'mouseReleased', x: 700, y: 420, button: 'left', buttons: 0, clickCount: 1 });
  await sl(1200);
  console.log('click   ' + await report('C'));
  // wheel zoom
  for (let i = 0; i < 12; i++) {
    await cdp.send('Input.dispatchMouseEvent', { type: 'mouseWheel', x: 700, y: 420, deltaX: 0, deltaY: -120, buttons: 0 });
    await sl(60);
  }
  await sl(1200);
  console.log('wheel   ' + await report('W'));
  await b.close().catch(() => {}); process.exit(0);
})().catch((e) => { console.log('DRIVER ' + e); process.exit(1); });
