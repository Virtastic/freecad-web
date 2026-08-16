// Where exactly does the drag suspend? Capture the full stack of the SuspendError.
const puppeteer = require('puppeteer-core');
const CHROME = process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';  // set CHROME_PATH to run off macOS
const sl = (ms) => new Promise((r) => setTimeout(r, ms));
const run = (p, c) => p.evaluate((code) => {
  const m = window.fcInstance;
  const n = new TextEncoder().encode(code).length + 1; const q = m._malloc(n); m.stringToUTF8(code, q, n);
  (window.fcRunPy || ((mm, pp) => { mm._fcweb_run_python(pp); mm._free(pp); }))(m, q);
}, c);
const readLog = (p) => p.evaluate(() => document.getElementById('log').textContent);
const grab = async (p, k) => { const m = (await readLog(p)).match(new RegExp(k + ' [^\\n]*', 'g')) || []; return m.length ? m[m.length-1] : '(none)'; };
const PY = (l) => l.join('\n');
(async () => {
  const b = await puppeteer.launch({ executablePath: CHROME, headless: false, defaultViewport: null,
    args: ['--no-sandbox','--use-gl=angle','--use-angle=metal','--window-size=1400,900'],
    protocolTimeout: 1800000, userDataDir: '/tmp/fc-dragtrace' });
  const p = (await b.pages())[0];
  const stacks = [];
  p.on('pageerror', (e) => stacks.push((e.stack || String(e)).split('\n').slice(0, 14).join('\n')));
  await p.goto(process.argv[2] || 'http://localhost:8792/index.html', { waitUntil: 'domcontentloaded', timeout: 300000 });
  const t0 = Date.now();
  while (Date.now() - t0 < 300000) { if (await p.evaluate(() => !!(window.fcInstance && window.fcInstance._malloc))) break; await sl(1000); }
  for (let i=0;i<40;i++){ await sl(3000); await run(p,'import sys,FreeCAD\nsys.__stderr__.write("RDY %d\\n"%len(FreeCAD.__unit_test__))\nsys.__stderr__.flush()\n'); await sl(1200);
    const m=[...(await readLog(p)).matchAll(/RDY (\d+)/g)].pop(); if(m&&+m[1]>0) break; }
  await run(p, PY([
    'import FreeCAD as App, FreeCADGui as Gui',
    'from PySide6 import QtWidgets',
    'd = App.newDocument("DT")',
    'g = d.addObject("App::DocumentObjectGroup","Bucket")',
    'o = d.addObject("Part::Box","Loose"); o.Length=o.Width=o.Height=10; d.recompute()',
    'Gui.activateWorkbench("PartWorkbench")',
    'mw = Gui.getMainWindow()',
    'for dw in mw.findChildren(QtWidgets.QDockWidget):',
    '    if "model" in dw.windowTitle().strip().lower(): dw.show(); dw.raise_()'
  ]));
  await sl(6000);
  const loc = async (label) => {
    await run(p, PY([
      'import sys',
      'from PySide6 import QtWidgets, QtCore',
      'import FreeCADGui as Gui',
      'mw = Gui.getMainWindow(); out="none"',
      'for t in mw.findChildren(QtWidgets.QTreeWidget):',
      '    if not t.isVisible(): continue',
      '    m = t.model()',
      '    r = m.match(m.index(0,0), QtCore.Qt.DisplayRole, "' + label + '", 1, QtCore.Qt.MatchRecursive|QtCore.Qt.MatchExactly)',
      '    if r:',
      '        t.expandAll(); t.scrollTo(r[0]); g = t.viewport().mapToGlobal(t.visualRect(r[0]).center())',
      '        if g.x()>0 and g.y()>0: out = "%d %d" % (g.x(), g.y()); break',
      'sys.__stderr__.write("L' + label + ' %s\\n" % out); sys.__stderr__.flush()'
    ]));
    await sl(2200);
    return /L\w+ (\d+) (\d+)/.exec(await grab(p, 'L' + label));
  };
  const s = await loc('Loose'), t = await loc('Bucket');
  console.log('src=' + (s && s[0]) + ' dst=' + (t && t[0]));
  if (s && t) {
    await p.mouse.move(+s[1], +s[2]); await sl(400); await p.mouse.down(); await sl(400);
    for (let i = 1; i <= 10; i++) { await p.mouse.move(+s[1] + (+t[1]-+s[1])*i/10, +s[2] + (+t[2]-+s[2])*i/10); await sl(160); }
    await sl(600); await p.mouse.up(); await sl(4000);
  }
  console.log('--- stacks (' + stacks.length + ') ---');
  stacks.slice(0, 2).forEach((st) => console.log(st + '\n'));
  // does the app still work after the failed drag?
  await run(p, PY([
    'import sys, FreeCAD as App',
    'd = App.getDocument("DT")',
    'o = d.addObject("Part::Sphere","After"); d.recompute()',
    'sys.__stderr__.write("ALIVE %s\\n" % [x.Name for x in d.Objects]); sys.__stderr__.flush()'
  ]));
  await sl(2500);
  console.log('after the failed drag: ' + await grab(p, 'ALIVE'));
  await b.close().catch(()=>{}); process.exit(0);
})().catch((e)=>{console.log('DRIVER '+String(e).slice(0,200));process.exit(0);});
