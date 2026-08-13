// Click a solid in the 3D view -- aimed with FreeCAD's OWN projection (getPointOnScreen),
// so an empty result means picking is broken, not that I missed.
const puppeteer = require('puppeteer-core');
const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const sl = (ms) => new Promise((r) => setTimeout(r, ms));
const run = (p, c) => p.evaluate((code) => {
  const m = window.fcInstance;
  const n = new TextEncoder().encode(code).length + 1; const q = m._malloc(n); m.stringToUTF8(code, q, n);
  (window.fcRunPy || ((mm, pp) => { mm._fcweb_run_python(pp); mm._free(pp); }))(m, q);
}, c);
const readLog = (p) => p.evaluate(() => document.getElementById('log').textContent);
const grab = async (p, k) => { const m = (await readLog(p)).match(new RegExp(k + ' [^\\n]*', 'g')) || []; return m.length ? m[m.length-1] : '(none)'; };
(async () => {
  const b = await puppeteer.launch({ executablePath: CHROME, headless: false, defaultViewport: null,
    args: ['--no-sandbox','--use-gl=angle','--use-angle=metal','--window-size=1400,900'],
    protocolTimeout: 1800000, userDataDir: '/tmp/fc-pick3d' });
  const p = (await b.pages())[0];
  const errs = []; p.on('pageerror', (e) => errs.push(String(e).slice(0,120)));
  await p.goto(process.argv[2] || 'http://localhost:8792/index.html', { waitUntil: 'domcontentloaded', timeout: 300000 });
  const t0 = Date.now();
  while (Date.now() - t0 < 300000) { if (await p.evaluate(() => !!(window.fcInstance && window.fcInstance._malloc))) break; await sl(1000); }
  for (let i=0;i<40;i++){ await sl(3000); await run(p,'import sys,FreeCAD\nsys.__stderr__.write("RDY %d\\n"%len(FreeCAD.__unit_test__))\nsys.__stderr__.flush()\n'); await sl(1200);
    const m=[...(await readLog(p)).matchAll(/RDY (\d+)/g)].pop(); if(m&&+m[1]>0) break; }

  await run(p, [
    'import sys',
    'import FreeCAD as App, FreeCADGui as Gui',
    'from PySide6 import QtWidgets, QtCore',
    'd = App.newDocument("PK")',
    'o = d.addObject("Part::Box","Solid"); o.Length=o.Width=o.Height=20; d.recompute()',
    'Gui.activateWorkbench("PartWorkbench")',
    'Gui.SendMsgToActiveView("ViewAxonometric"); Gui.SendMsgToActiveView("ViewFit")',
    'v = Gui.ActiveDocument.ActiveView',
    // centre of the top face: (10,10,20)
    'sp = v.getPointOnScreen(10.0,10.0,20.0)',
    'w = v.getViewer() if hasattr(v,"getViewer") else None',
    'mdi = Gui.getMainWindow().findChild(QtWidgets.QMdiArea); sub = mdi.currentSubWindow()',
    'sys.__stderr__.write("PROJ %s SUB %d %d %d %d\\n" % (sp, sub.mapToGlobal(QtCore.QPoint(0,0)).x(), sub.mapToGlobal(QtCore.QPoint(0,0)).y(), sub.width(), sub.height()))',
    'sys.__stderr__.flush()'
  ].join('\n'));
  await sl(6000);
  const proj = await grab(p, 'PROJ');
  console.log('projection: ' + proj);
  const m = /PROJ \(([-\d.]+), ?([-\d.]+)\) SUB (\d+) (\d+) (\d+) (\d+)/.exec(proj);
  if (!m) { console.log('could not read projection; aborting'); await b.close(); process.exit(0); }
  const px = Math.round(+m[1]), py = Math.round(+m[2]);
  const ox = +m[3], oy = +m[4], sh = +m[6];
  // getPointOnScreen is bottom-left origin in viewport coords -> flip Y, offset by subwindow
  const gx = ox + px, gy = oy + (sh - py);
  console.log(`clicking global (${gx}, ${gy})  [viewport ${px},${py} in ${m[5]}x${sh}]`);
  await run(p, 'import FreeCADGui as Gui\nGui.Selection.clearSelection()\n');
  await sl(1200);
  await p.mouse.click(gx, gy); await sl(2500);
  await run(p, 'import sys, FreeCADGui as Gui\nsys.__stderr__.write("SEL1 %s\\n" % [(o.Name) for o in Gui.Selection.getSelection()])\nsys.__stderr__.flush()\n');
  await sl(1800);
  console.log('after click on the solid: ' + await grab(p, 'SEL1'));
  // and a click on empty space should clear it
  await p.mouse.click(ox + 15, oy + 15); await sl(2000);
  await run(p, 'import sys, FreeCADGui as Gui\nsys.__stderr__.write("SEL2 %s\\n" % [(o.Name) for o in Gui.Selection.getSelection()])\nsys.__stderr__.flush()\n');
  await sl(1800);
  console.log('after click on empty space: ' + await grab(p, 'SEL2'));
  // preselection (hover) too
  await p.mouse.move(gx, gy); await sl(2000);
  await run(p, 'import sys, FreeCADGui as Gui\nd=Gui.Selection.getPreselection()\nsys.__stderr__.write("PRE %s\\n" % (d.Object.Name if d and d.Object else None))\nsys.__stderr__.flush()\n');
  await sl(1800);
  console.log('hover preselection: ' + await grab(p, 'PRE'));
  console.log('page errors: ' + (errs.length ? errs.slice(0,3).join(' | ') : 'none'));
  await b.close().catch(()=>{}); process.exit(0);
})().catch((e)=>{console.log('DRIVER '+String(e).slice(0,200));process.exit(0);});
