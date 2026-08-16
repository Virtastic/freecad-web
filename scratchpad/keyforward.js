// Can the shell hand keys to Qt when no text widget has focus?
// Qt-wasm registers its own DOM listeners; re-dispatching the real KeyboardEvent onto the
// element Qt listens to should give GENERAL keyboard support, not a hardcoded shortcut map.
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
    protocolTimeout: 1800000, userDataDir: '/tmp/fc-keyfwd' });
  const p = (await b.pages())[0];
  await p.goto(process.argv[2] || 'http://localhost:8792/index.html', { waitUntil: 'domcontentloaded', timeout: 300000 });
  const t0 = Date.now();
  while (Date.now() - t0 < 300000) { if (await p.evaluate(() => !!(window.fcInstance && window.fcInstance._malloc))) break; await sl(1000); }
  for (let i=0;i<40;i++){ await sl(3000); await run(p,'import sys,FreeCAD\nsys.__stderr__.write("RDY %d\\n"%len(FreeCAD.__unit_test__))\nsys.__stderr__.flush()\n'); await sl(1200);
    const m=[...(await readLog(p)).matchAll(/RDY (\d+)/g)].pop(); if(m&&+m[1]>0) break; }

  // what DOM elements exist inside Qt's shadow root, and which look like key targets?
  console.log(JSON.stringify(await p.evaluate(() => {
    const hosts = [...document.querySelectorAll('*')].filter(e => e.shadowRoot);
    const out = [];
    for (const h of hosts) {
      for (const el of h.shadowRoot.querySelectorAll('*')) {
        out.push({ tag: el.tagName, id: el.id || null, cls: (el.className && el.className.baseVal !== undefined ? el.className.baseVal : el.className) || null,
                   tabindex: el.getAttribute('tabindex'), ce: el.getAttribute('contenteditable') });
      }
    }
    return { hostCount: hosts.length, elements: out.slice(0, 14) };
  }), null, 1));

  await run(p, [
    'import sys',
    'import FreeCAD as App, FreeCADGui as Gui',
    'from PySide6 import QtWidgets, QtCore',
    'def say(m): sys.__stderr__.write(m+"\\n"); sys.__stderr__.flush()',
    'd = App.newDocument("Fwd"); d.addObject("Part::Box","Target"); d.recompute()',
    'mw = Gui.getMainWindow()',
    'tree = [t for t in mw.findChildren(QtWidgets.QTreeWidget) if t.isVisible()][0]',
    'tree.setFocus(QtCore.Qt.MouseFocusReason)',
    'Gui.Selection.clearSelection(); Gui.Selection.addSelection(d.Name, "Target")',
    'class Spy(QtCore.QObject):',
    '    def eventFilter(self, o, e):',
    '        if int(e.type()) == 6:',
    '            try: k = e.key()',
    '            except Exception: k = -1',
    '            say("KEY %s on=%s" % (k, o.__class__.__name__))',
    '        return False',
    'sp = Spy(mw); mw._fwdSpy = sp; QtWidgets.QApplication.instance().installEventFilter(sp)',
    'say("ARMED sel=%s" % [o.Name for o in Gui.Selection.getSelection()])'
  ].join('\n'));
  await sl(4000);
  console.log(await grab(p, 'ARMED'));

  // dispatch a real KeyboardEvent at each plausible Qt target and see which one Qt hears
  const targets = ['canvas', 'shadowHost', 'document', 'window'];
  for (const t of targets) {
    const before = ((await readLog(p)).match(/KEY \S+ on=\S+/g) || []).length;
    await p.evaluate((which) => {
      const hosts = [...document.querySelectorAll('*')].filter(e => e.shadowRoot);
      const canvas = hosts.flatMap(h => [...h.shadowRoot.querySelectorAll('canvas')])[0];
      const ev = () => new KeyboardEvent('keydown', { key: 'Delete', code: 'Delete', keyCode: 46,
                                                      which: 46, bubbles: true, cancelable: true, composed: true });
      const tgt = which === 'canvas' ? canvas : which === 'shadowHost' ? hosts[0] : which === 'document' ? document : window;
      if (tgt) tgt.dispatchEvent(ev());
    }, t);
    await sl(1800);
    const after = ((await readLog(p)).match(/KEY \S+ on=\S+/g) || []).slice(before);
    console.log(`dispatch on ${t.padEnd(11)} -> Qt saw: ${after.length ? after.join(' | ') : 'nothing'}`);
  }
  await run(p, 'import sys, FreeCAD as App\nsys.__stderr__.write("FINAL objs=%s\\n" % [o.Name for o in App.getDocument("Fwd").Objects])\nsys.__stderr__.flush()\n');
  await sl(2000);
  console.log(await grab(p, 'FINAL'));
  await b.close().catch(()=>{}); process.exit(0);
})().catch((e)=>{console.log('DRIVER '+String(e).slice(0,200));process.exit(0);});
