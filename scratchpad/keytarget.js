// Which single DOM target, when a KeyboardEvent is dispatched on it, makes Qt act?
// Recreate the victim before each attempt and check deletion -- the deletion is the proof,
// not the event log (a shortcut fires QEvent::Shortcut, not KeyPress).
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
(async () => {
  const b = await puppeteer.launch({ executablePath: CHROME, headless: false, defaultViewport: null,
    args: ['--no-sandbox','--use-gl=angle','--use-angle=metal','--window-size=1400,900'],
    protocolTimeout: 1800000, userDataDir: '/tmp/fc-keytarget' });
  const p = (await b.pages())[0];
  await p.goto(process.argv[2] || 'http://localhost:8792/index.html', { waitUntil: 'domcontentloaded', timeout: 300000 });
  const t0 = Date.now();
  while (Date.now() - t0 < 300000) { if (await p.evaluate(() => !!(window.fcInstance && window.fcInstance._malloc))) break; await sl(1000); }
  for (let i=0;i<40;i++){ await sl(3000); await run(p,'import sys,FreeCAD\nsys.__stderr__.write("RDY %d\\n"%len(FreeCAD.__unit_test__))\nsys.__stderr__.flush()\n'); await sl(1200);
    const m=[...(await readLog(p)).matchAll(/RDY (\d+)/g)].pop(); if(m&&+m[1]>0) break; }
  await run(p, 'import sys, FreeCAD as App\nApp.newDocument("T")\nsys.__stderr__.write("DOC ok\\n")\nsys.__stderr__.flush()\n');
  await sl(3000);

  for (const which of ['canvas', 'shadowHost', 'document', 'window']) {
    await run(p, [
      'import sys',
      'import FreeCAD as App, FreeCADGui as Gui',
      'from PySide6 import QtWidgets, QtCore',
      'd = App.getDocument("T")',
      'for o in list(d.Objects): d.removeObject(o.Name)',
      'd.addObject("Part::Box","V"); d.recompute()',
      'mw = Gui.getMainWindow()',
      'tree = [t for t in mw.findChildren(QtWidgets.QTreeWidget) if t.isVisible()][0]',
      'tree.setFocus(QtCore.Qt.MouseFocusReason)',
      'Gui.Selection.clearSelection(); Gui.Selection.addSelection(d.Name, "V")',
      'sys.__stderr__.write("PRE %s\\n" % [o.Name for o in d.Objects]); sys.__stderr__.flush()'
    ].join('\n'));
    await sl(3000);
    await p.evaluate((w) => {
      const hosts = [...document.querySelectorAll('*')].filter(e => e.shadowRoot);
      const canvas = hosts.flatMap(h => [...h.shadowRoot.querySelectorAll('canvas')])[0];
      const tgt = w === 'canvas' ? canvas : w === 'shadowHost' ? hosts[0] : w === 'document' ? document : window;
      const mk = (type) => new KeyboardEvent(type, { key: 'Delete', code: 'Delete', keyCode: 46, which: 46,
                                                     bubbles: true, cancelable: true, composed: true });
      if (tgt) { tgt.dispatchEvent(mk('keydown')); tgt.dispatchEvent(mk('keyup')); }
    }, which);
    await sl(3000);
    await run(p, 'import sys, FreeCAD as App\nsys.__stderr__.write("POST %s\\n" % [o.Name for o in App.getDocument("T").Objects])\nsys.__stderr__.flush()\n');
    await sl(2000);
    const post = await grab(p, 'POST');
    console.log(`${which.padEnd(11)} -> ${post}   ${post.includes('[]') ? '*** DELETED (this target works) ***' : 'no effect'}`);
  }
  await b.close().catch(()=>{}); process.exit(0);
})().catch((e)=>{console.log('DRIVER '+String(e).slice(0,200));process.exit(0);});
