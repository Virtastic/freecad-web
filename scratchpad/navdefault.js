// After boot, with no explicit user choice: does a plain left-drag rotate, and does a
// plain left-click still select? Both must hold, or the default is a downgrade.
const puppeteer = require('puppeteer-core');
const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const sl = (ms) => new Promise((r) => setTimeout(r, ms));
const run = (p, c) => p.evaluate((c) => { const m = window.fcInstance;
  const n = new TextEncoder().encode(c).length + 1; const q = m._malloc(n); m.stringToUTF8(c, q, n);
  (window.fcRunPy || ((mm, pp) => { mm._fcweb_run_python(pp); mm._free(pp); }))(m, q); }, c);
const pw = async (p, mk, ms) => { const t0 = Date.now();
  while (Date.now() - t0 < ms) { try { if (await p.evaluate((k) =>
    document.getElementById('log').textContent.includes(k), mk)) return true; } catch (e) {} await sl(400); } return false; };
let seq = 0;
const cam = async (p) => { const tag = 'ND' + (++seq);
  await run(p, ['import FreeCADGui as Gui,sys', 'c=Gui.activeDocument().activeView().getCamera()',
    "q=[l.strip() for l in c.splitlines() if 'position' in l or 'orientation' in l]",
    "sys.__stderr__.write('" + tag + " %s\\n'%(' ; '.join(q[:2])))"].join('\n'));
  await pw(p, tag, 20000);
  const log = await p.evaluate(() => document.getElementById('log').textContent);
  return ((log.match(new RegExp(tag + '[^\\n]*')) || [''])[0]).replace(tag + ' ', ''); };
(async () => {
  const b = await puppeteer.launch({ executablePath: CHROME, headless: false, defaultViewport: null,
    args: ['--no-sandbox', '--use-gl=angle', '--use-angle=metal', '--window-size=1400,900'],
    protocolTimeout: 2400000, userDataDir: '/tmp/fc-navdefault-' + Date.now() });  // fresh home: no saved pref
  const p = (await b.pages())[0];
  await p.goto('http://localhost:8791/index.html', { waitUntil: 'domcontentloaded', timeout: 300000 });
  const t0 = Date.now();
  while (Date.now() - t0 < 300000) { if (await p.evaluate(() => !!(window.fcInstance && window.fcInstance._malloc))) break; await sl(1000); }
  await sl(10000);
  await run(p, ['import FreeCAD as App, FreeCADGui as Gui, sys', 'd=App.newDocument("N")',
    'd.addObject("Part::Box","B"); d.recompute()',
    'Gui.activeDocument().activeView().viewIsometric(); Gui.SendMsgToActiveView("ViewFit")',
    'sys.__stderr__.write("STYLE %s\\n" % Gui.activeDocument().activeView().getNavigationType())',
    'sys.__stderr__.write("READY\\n")'].join('\n'));
  await pw(p, 'READY', 120000); await sl(3000);
  const log0 = await p.evaluate(() => document.getElementById('log').textContent);
  console.log('active style: ' + ((log0.match(/STYLE [^\n]*/g) || ['?']).pop()));
  const c = await p.evaluate(() => { const h = document.getElementById('qt-shadow-container');
    const cv = h && h.shadowRoot && h.shadowRoot.querySelector('canvas');
    const r = (cv || document.body).getBoundingClientRect();
    return { x: r.x + r.width * 0.55, y: r.y + r.height * 0.5 }; });
  const a = await cam(p);
  await p.mouse.move(c.x, c.y); await p.mouse.down({ button: 'left' });
  for (let i = 1; i <= 15; i++) { await p.mouse.move(c.x + i * 8, c.y - i * 4); await sl(25); }
  await p.mouse.up({ button: 'left' }); await sl(1200);
  const z = await cam(p);
  console.log('left-drag rotates: ' + (a.split(' ; ')[1] !== z.split(' ; ')[1]));
  await run(p, 'import FreeCADGui as Gui\nGui.Selection.clearSelection()');
  await sl(600);
  await p.mouse.move(c.x, c.y); await p.mouse.down({ button: 'left' }); await sl(60); await p.mouse.up({ button: 'left' });
  await sl(1200);
  await run(p, 'import FreeCADGui as Gui, sys\nsys.__stderr__.write("SEL %d\\n" % len(Gui.Selection.getSelection()))');
  await pw(p, 'SEL', 15000);
  const log = await p.evaluate(() => document.getElementById('log').textContent);
  console.log('left-click still selects: ' + ((log.match(/SEL \d+/g) || ['?']).pop()));
  await b.close().catch(() => {}); process.exit(0);
})().catch((e) => { console.log('DRIVER ' + e); process.exit(1); });
