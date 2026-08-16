// Why does the Delete key not delete? Two candidates: the key never reaches Qt's shortcut
// machinery, or the Std_Delete action is disabled at that moment (FreeCAD refreshes action
// enablement on a 150 ms timer). Instrument both.
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
    protocolTimeout: 1800000, userDataDir: '/tmp/fc-delkey' });
  const p = (await b.pages())[0];
  await p.goto(process.argv[2] || 'http://localhost:8792/index.html', { waitUntil: 'domcontentloaded', timeout: 300000 });
  const t0 = Date.now();
  while (Date.now() - t0 < 300000) { if (await p.evaluate(() => !!(window.fcInstance && window.fcInstance._malloc))) break; await sl(1000); }
  for (let i=0;i<40;i++){ await sl(3000); await run(p,'import sys,FreeCAD\nsys.__stderr__.write("RDY %d\\n"%len(FreeCAD.__unit_test__))\nsys.__stderr__.flush()\n'); await sl(1200);
    const m=[...(await readLog(p)).matchAll(/RDY (\d+)/g)].pop(); if(m&&+m[1]>0) break; }

  await run(p, [
    'import sys',
    'import FreeCAD as App, FreeCADGui as Gui',
    'from PySide6 import QtWidgets, QtCore',
    'def say(m):',
    '    sys.__stderr__.write(m + "\\n"); sys.__stderr__.flush()',
    'try:',
    '    d = App.newDocument("DelKey")',
    '    b = d.addObject("Part::Box","Victim"); d.recompute()',
    '    mw = Gui.getMainWindow()',
    '    tree = [t for t in mw.findChildren(QtWidgets.QTreeWidget) if t.isVisible()][0]',
    '    tree.setFocus(QtCore.Qt.MouseFocusReason)',
    '    Gui.Selection.clearSelection(); Gui.Selection.addSelection(d.Name, "Victim")',
    'except Exception as e:',
    '    say("SETUPEXC %s" % e)',
    'try:',
    '    info = Gui.Command.get("Std_Delete").getInfo()',
    '    say("ACTION shortcut=%r active=%s" % (info.get("shortcut"), Gui.Command.get("Std_Delete").isActive()))',
    'except Exception as e:',
    '    say("ACTION EXC %s" % str(e)[:90])',
    'try:',
    '    acts = [a for a in mw.actions()] ',
    '    named = [a for a in mw.findChildren(QtCore.QObject) if a.metaObject().className() == "QAction" and a.objectName() == "Std_Delete"]',
    '    for a in named[:1]:',
    '        say("QACTION enabled=%s shortcut=%s" % (a.property("enabled"), a.property("shortcut")))',
    '    if not named: say("QACTION not-found-by-name")',
    'except Exception as e:',
    '    say("QACTION EXC %s" % str(e)[:90])',
    'try:',
    '    class Spy(QtCore.QObject):',
    '        def eventFilter(self, o, e):',
    '            t = int(e.type())',
    '            if t in (6, 51, 117):',
    '                try: k = e.key()',
    '                except Exception: k = -1',
    '                say("EV t=%d key=%s on=%s" % (t, k, o.__class__.__name__))',
    '            return False',
    '    spy = Spy(mw); mw._delSpy = spy',
    '    QtWidgets.QApplication.instance().installEventFilter(spy)',
    '    say("SPY installed")',
    'except Exception as e:',
    '    say("SPY EXC %s" % str(e)[:90])',
    'say("READY objs=%s sel=%s" % ([o.Name for o in App.getDocument("DelKey").Objects],',
    '    [o.Name for o in Gui.Selection.getSelection()]))'
  ].join('\n'));
  await sl(5000);
  console.log(await grab(p, 'ACTION'));
  console.log(await grab(p, 'READY'));

  await p.keyboard.press('Delete');
  await sl(3000);
  const evs = ((await readLog(p)).match(/EV \d+ key=\S+ on=\S+/g) || []);
  console.log('Qt events seen for the Delete press: ' + (evs.length ? evs.slice(-8).join(' | ') : 'NONE'));
  console.log('  (type 6=KeyPress 51=ShortcutOverride 117=Shortcut; Qt::Key_Delete=16777223)');
  await run(p, 'import sys, FreeCAD as App\nsys.__stderr__.write("AFTER objs=%s\\n" % [o.Name for o in App.getDocument("DelKey").Objects])\nsys.__stderr__.flush()\n');
  await sl(2000);
  console.log(await grab(p, 'AFTER'));
  await b.close().catch(()=>{}); process.exit(0);
})().catch((e)=>{console.log('DRIVER '+String(e).slice(0,200));process.exit(0);});
