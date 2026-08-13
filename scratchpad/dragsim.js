// Chrome will not begin a native HTML5 drag from CDP-synthesised mouse input, so the
// drag pipeline is driven directly: real mouse press + moves make Qt call QDrag::exec
// (which is what used to throw SuspendError), then the DOM drag events Qt is waiting for
// are dispatched onto its canvas -- exactly what the browser would send a real user.
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
const PY = (l) => l.join('\n');
(async () => {
  const b = await puppeteer.launch({ executablePath: CHROME, headless: false, defaultViewport: null,
    args: ['--no-sandbox','--use-gl=angle','--use-angle=metal','--window-size=1400,900'],
    protocolTimeout: 600000, userDataDir: '/tmp/fc-dragsim' });
  const p = (await b.pages())[0];
  const errs = []; p.on('pageerror', (e) => errs.push(String(e).split('\n')[0].slice(0,140)));
  await p.goto(process.argv[2] || 'http://localhost:8792/index.html', { waitUntil: 'domcontentloaded', timeout: 300000 });
  const t0 = Date.now();
  while (Date.now() - t0 < 300000) { if (await p.evaluate(() => !!(window.fcInstance && window.fcInstance._malloc))) break; await sl(1000); }
  for (let i=0;i<40;i++){ await sl(3000); await run(p,'import sys,FreeCAD\nsys.__stderr__.write("RDY %d\\n"%len(FreeCAD.__unit_test__))\nsys.__stderr__.flush()\n'); await sl(1200);
    const m=[...(await readLog(p)).matchAll(/RDY (\d+)/g)].pop(); if(m&&+m[1]>0) break; }

  await run(p, PY([
    'import FreeCAD as App, FreeCADGui as Gui',
    'from PySide6 import QtWidgets',
    'd = App.newDocument("DS")',
    'd.addObject("App::DocumentObjectGroup","Bucket")',
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
  if (!s || !t) { console.log('items not locatable'); await b.close(); process.exit(0); }
  const A = { x: +s[1], y: +s[2] }, B = { x: +t[1], y: +t[2] };
  console.log(`drag ${A.x},${A.y} -> ${B.x},${B.y}`);

  // 1. press and move: Qt decides a drag has started and calls QDrag::exec
  await p.mouse.move(A.x, A.y); await sl(300);
  await p.mouse.down(); await sl(300);
  await p.mouse.move(A.x, A.y - 6); await sl(150);
  await p.mouse.move(A.x, A.y - 14); await sl(400);

  // 2. the DOM drag sequence Qt is waiting for, onto its own canvas
  const fired = await p.evaluate((ax, ay, bx, by) => {
    function canvas(root) {
      for (const el of root.querySelectorAll('*')) {
        if (el.tagName === 'CANVAS') return el;
        if (el.shadowRoot) { const c = canvas(el.shadowRoot); if (c) return c; }
      }
      return null;
    }
    const c = canvas(document);
    if (!c) return 'no canvas';
    const dt = new DataTransfer();
    const ev = (type, x, y) => c.dispatchEvent(new DragEvent(type, {
      bubbles: true, cancelable: true, composed: true, dataTransfer: dt,
      clientX: x, clientY: y, screenX: x, screenY: y
    }));
    ev('dragstart', ax, ay);
    ev('dragenter', bx, by);
    ev('dragover', bx, by);
    ev('drop', bx, by);
    ev('dragend', bx, by);
    return 'dispatched on ' + c.tagName + ' ' + c.width + 'x' + c.height;
  }, A.x, A.y, B.x, B.y);
  console.log('drag events: ' + fired);
  await sl(1000);
  await p.mouse.up(); await sl(4000);

  await run(p, PY([
    'import sys, FreeCAD as App',
    'sys.__stderr__.write("GROUP %s\\n" % [o.Name for o in App.getDocument("DS").getObject("Bucket").Group]); sys.__stderr__.flush()'
  ]));
  await sl(2500);
  const gr = await grab(p, 'GROUP');
  console.log(`tree drag-and-drop: ${gr}  ${gr.includes('Loose') ? '*** the drop reparented it ***' : '(not reparented)'}`);
  console.log('page errors: ' + (errs.length ? errs.slice(0,3).join(' | ') : 'none'));
  await b.close().catch(()=>{}); process.exit(0);
})().catch((e)=>{console.log('DRIVER '+String(e).slice(0,200));process.exit(0);});
