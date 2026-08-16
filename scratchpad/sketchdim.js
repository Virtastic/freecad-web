// A dimensional constraint is the deepest everyday use of a modal dialog: mid-workflow,
// inside Sketcher's edit mode, opened from a real toolbar/keyboard action, and the value
// typed into it must reach the geometry. Before the promising fix this dialog could not
// open from real input at all.
const puppeteer = require('puppeteer-core');
const CHROME = process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';  // set CHROME_PATH to run off macOS
const sl = (ms) => new Promise((r) => setTimeout(r, ms));
const MOD = process.platform === 'darwin' ? 'Meta' : 'Control';
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
    protocolTimeout: 900000, userDataDir: '/tmp/fc-sketchdim' });
  const p = (await b.pages())[0];
  const errs = []; p.on('pageerror', (e) => errs.push(String(e).split('\n')[0].slice(0,140)));
  await p.goto(process.argv[2] || 'http://localhost:8792/index.html', { waitUntil: 'domcontentloaded', timeout: 300000 });
  const t0 = Date.now();
  while (Date.now() - t0 < 300000) { if (await p.evaluate(() => !!(window.fcInstance && window.fcInstance._malloc))) break; await sl(1000); }
  for (let i=0;i<40;i++){ await sl(3000); await run(p,'import sys,FreeCAD\nsys.__stderr__.write("RDY %d\\n"%len(FreeCAD.__unit_test__))\nsys.__stderr__.flush()\n'); await sl(1200);
    const m=[...(await readLog(p)).matchAll(/RDY (\d+)/g)].pop(); if(m&&+m[1]>0) break; }

  // a sketch with one line, opened in edit mode; select the line so a constraint applies to it
  await run(p, PY([
    'import sys',
    'import FreeCAD as App, FreeCADGui as Gui, Part, Sketcher',
    'd = App.newDocument("SD")',
    'sk = d.addObject("Sketcher::SketchObject","Sketch")',
    'sk.addGeometry(Part.LineSegment(App.Vector(0,0,0), App.Vector(30,0,0)), False)',
    'd.recompute()',
    'Gui.activateWorkbench("SketcherWorkbench")',
    'Gui.ActiveDocument.setEdit(sk)',
    'Gui.SendMsgToActiveView("ViewFit")',
    'Gui.Selection.clearSelection()',
    'Gui.Selection.addSelection(d.Name, sk.Name, "Edge1")',
    'sys.__stderr__.write("SETUP len=%.3f sel=%d\\n" % (sk.Geometry[0].length(), len(Gui.Selection.getSelectionEx()))); sys.__stderr__.flush()'
  ]));
  await sl(8000);
  console.log(await grab(p, 'SETUP'));

  // press K,D? -- upstream binds distance to "K,D" in 1.0; the direct command is safer to
  // locate, so click its toolbar action for real
  await run(p, PY([
    'import sys',
    'from PySide6 import QtWidgets',
    'import FreeCADGui as Gui',
    'mw = Gui.getMainWindow(); out="none"; names=[]',
    'for tb in mw.findChildren(QtWidgets.QToolBar):',
    '    if not tb.isVisible(): continue',
    '    for a in tb.actions():',
    '        t = (a.objectName() or a.text() or "").replace("&","").strip()',
    '        if not a.isVisible() or not a.isEnabled(): continue',
    '        names.append(a.objectName() or t)',
    '        if a.objectName() in ("Sketcher_ConstrainDistance","Sketcher_Dimension","Sketcher_ConstrainDistanceX"):',
    '            w = tb.widgetForAction(a)',
    '            if w and w.isVisible():',
    '                g = w.mapToGlobal(w.rect().center())',
    '                if out == "none": out="%d %d"%(g.x(),g.y())',
    'sys.__stderr__.write("DISTBTN %s\\n" % out); sys.__stderr__.flush()',
    'sys.__stderr__.write("ACTIONS %s\\n" % [n for n in names if "onstrain" in n or "imension" in n][:12]); sys.__stderr__.flush()'
  ]));
  await sl(2500);
  const db = /DISTBTN (\d+) (\d+)/.exec(await grab(p, 'DISTBTN'));
  console.log('distance constraint button: ' + await grab(p, 'DISTBTN'));
  console.log('sketcher constraint actions present: ' + await grab(p, 'ACTIONS'));
  if (!db) { console.log('button not found -- cannot drive this by click'); }
  else {
    const before = errs.length;
    await p.mouse.click(+db[1], +db[2]); await sl(5000);
    await run(p, PY([
      'import sys',
      'from PySide6 import QtWidgets',
      'ds = [(type(w).__name__, w.windowTitle()) for w in QtWidgets.QApplication.topLevelWidgets() if isinstance(w, QtWidgets.QDialog) and w.isVisible()]',
      'sys.__stderr__.write("DIMDLG %s\\n" % ds); sys.__stderr__.flush()'
    ]));
    await sl(2500);
    const dd = await grab(p, 'DIMDLG');
    const ne = errs.slice(before);
    console.log(`dimension dialog: ${dd}  errors=${ne.length ? ne.join(' | ') : 'none'}`);
    if (/QDialog|Insert/.test(dd)) {
      // type a new length and accept, all with real input
      await p.keyboard.down(MOD); await p.keyboard.press('KeyA'); await p.keyboard.up(MOD); await sl(400);
      await p.keyboard.type('45', { delay: 130 }); await sl(800);
      await p.keyboard.press('Enter'); await sl(5000);
      await run(p, PY([
        'import sys, FreeCAD as App',
        'sk = App.getDocument("SD").getObject("Sketch")',
        'App.getDocument("SD").recompute()',
        'sys.__stderr__.write("AFTER len=%.3f cons=%d dof=%s\\n" % (sk.Geometry[0].length(), len(sk.Constraints), sk.solve())); sys.__stderr__.flush()'
      ]));
      await sl(3000);
      const af = await grab(p, 'AFTER');
      console.log(`after typing 45: ${af}  ${/len=45\.000/.test(af) ? '*** the typed dimension reached the geometry ***' : '(length unchanged)'}`);
    } else {
      console.log('  no dialog appeared -- the constraint may have been applied inline');
      await run(p, PY([
        'import sys, FreeCAD as App',
        'sk = App.getDocument("SD").getObject("Sketch")',
        'sys.__stderr__.write("INLINE len=%.3f cons=%d\\n" % (sk.Geometry[0].length(), len(sk.Constraints))); sys.__stderr__.flush()'
      ]));
      await sl(2500);
      console.log('  ' + await grab(p, 'INLINE'));
    }
  }
  // leave edit mode cleanly and confirm the app is healthy
  await run(p, PY([
    'import sys, FreeCADGui as Gui, FreeCAD as App',
    'Gui.ActiveDocument.resetEdit()',
    'd = App.getDocument("SD"); d.addObject("Part::Box","Alive"); d.recompute()',
    'sys.__stderr__.write("ALIVE %s\\n" % [o.Name for o in d.Objects]); sys.__stderr__.flush()'
  ]));
  await sl(3000);
  console.log('after leaving edit mode: ' + await grab(p, 'ALIVE'));
  console.log('page errors: ' + (errs.length ? errs.slice(0,4).join(' | ') : 'none'));
  await b.close().catch(()=>{}); process.exit(0);
})().catch((e)=>{console.log('DRIVER '+String(e).slice(0,200));process.exit(0);});
