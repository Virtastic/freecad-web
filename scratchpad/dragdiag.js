// Where is the 3D viewport, does setNavigationType take, and which button actually
// orbits? Everything else was measuring a drag that never reached the camera.
const puppeteer = require('puppeteer-core');
const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
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
    protocolTimeout: 2400000, userDataDir: '/tmp/fc-dragdiag' });
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

  console.log('canvas rect: ' + JSON.stringify(await p.evaluate(() => {
    const find = (root) => { const c = root.querySelector && root.querySelector('canvas'); if (c) return c;
      for (const el of (root.querySelectorAll ? root.querySelectorAll('*') : [])) {
        if (el.shadowRoot) { const r = find(el.shadowRoot); if (r) return r; } } return null; };
    const c = find(document); if (!c) return 'no canvas';
    const r = c.getBoundingClientRect();
    return { x: Math.round(r.left), y: Math.round(r.top), w: Math.round(r.width), h: Math.round(r.height),
             dpr: devicePixelRatio, win: [innerWidth, innerHeight] };
  })));
  await run(p, 'import FreeCADGui as Gui, sys\nav=Gui.ActiveDocument.ActiveView\n' +
    'sys.__stderr__.write("NAV0 %s\\n" % av.getNavigationType())\n' +
    'try:\n av.setNavigationType("Gui::GestureNavigationStyle")\n' +
    ' sys.__stderr__.write("NAV1 %s\\n" % av.getNavigationType())\n' +
    'except Exception as e:\n sys.__stderr__.write("NAVERR %s\\n" % e)\n');
  await sl(1200);
  console.log('nav before: ' + await tail(p, /NAV0 [^\n]*/g));
  console.log('nav after : ' + await tail(p, /NAV1 [^\n]*/g) + '  ' + await tail(p, /NAVERR [^\n]*/g));

  const cam = async (tag) => { await run(p, 'import FreeCADGui as Gui, sys\nc=Gui.ActiveDocument.ActiveView.getCameraNode()\n' +
      'sys.__stderr__.write("' + tag + ' %s\\n" % (tuple(c.orientation.getValue().getValue()),))\n'); await sl(700);
    return await tail(p, new RegExp(tag + ' \\\\([^)]*\\\\)', 'g')); };

  for (const [name, btn, buttons] of [['left', 'left', 1], ['middle', 'middle', 4], ['right', 'right', 2]]) {
    const before = await cam('C_' + name + '_A');
    const mv = (x, y, type) => cdp.send('Input.dispatchMouseEvent', { type, x, y, button: btn, buttons, clickCount: 1 });
    await mv(700, 480, 'mousePressed');
    for (let i = 0; i < 25; i++) { await mv(700 + i * 6, 480 + i * 3, 'mouseMoved'); }
    await cdp.send('Input.dispatchMouseEvent', { type: 'mouseReleased', x: 850, y: 555, button: btn, buttons: 0, clickCount: 1 });
    await sl(900);
    const after = await cam('C_' + name + '_B');
    console.log(name.padEnd(7) + ' orbit: ' + (before.slice(before.indexOf('(')) !== after.slice(after.indexOf('(')) ? 'CAMERA MOVED' : 'no change'));
  }
  await b.close().catch(() => {}); process.exit(0);
})().catch((e) => { console.log('DRIVER ' + e); process.exit(1); });
