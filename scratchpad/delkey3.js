// Does the Delete key delete? Third attempt, with both traps from the previous two closed:
//   - CLICK into the app first, so DOM focus is on the Qt canvas (a programmatic
//     tree.setFocus() does not move the browser's focus, and the key goes nowhere).
//   - WAIT from the harness before reading action enablement: FreeCAD refreshes it on a
//     150 ms timer, so reading it in the same Python call that set the selection is stale.
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
    protocolTimeout: 1800000, userDataDir: '/tmp/fc-delkey3' });
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
    'def say(m): sys.__stderr__.write(m+"\\n"); sys.__stderr__.flush()',
    'd = App.newDocument("DelKey3")',
    'd.addObject("Part::Box","Victim"); d.recompute()',
    'Gui.SendMsgToActiveView("ViewFit")',
    'mw = Gui.getMainWindow()',
    'for tb in mw.findChildren(QtWidgets.QTabBar):',
    '    for i in range(tb.count()):',
    '        if tb.tabText(i).strip().lower() == "model":',
    '            g = tb.mapToGlobal(tb.tabRect(i).center()); say("TAB %d %d" % (g.x(), g.y()))',
    'class Spy(QtCore.QObject):',
    '    def eventFilter(self, o, e):',
    '        t = int(e.type())',
    '        if t in (6, 51, 117):',
    '            try: k = e.key()',
    '            except Exception: k = -1',
    '            say("EV t=%d key=%s on=%s" % (t, k, o.__class__.__name__))',
    '        return False',
    'spy = Spy(mw); mw._spy3 = spy; QtWidgets.QApplication.instance().installEventFilter(spy)',
    'say("SETUP objs=%s" % [o.Name for o in d.Objects])'
  ].join('\n'));
  await sl(4000);
  const tab = /TAB (\d+) (\d+)/.exec(await grab(p, 'TAB'));
  if (tab) { await p.mouse.click(+tab[1], +tab[2]); await sl(2500); }   // real click -> canvas has DOM focus

  // click the tree item itself, like a user
  await run(p, [
    'import sys',
    'from PySide6 import QtWidgets, QtCore',
    'import FreeCADGui as Gui',
    'def say(m): sys.__stderr__.write(m+"\\n"); sys.__stderr__.flush()',
    'mw = Gui.getMainWindow()',
    'hit = None',
    'for t in mw.findChildren(QtWidgets.QTreeWidget):',
    '    if not t.isVisible(): continue',
    '    m = t.model()',
    '    r = m.match(m.index(0,0), QtCore.Qt.DisplayRole, "Victim", 1, QtCore.Qt.MatchRecursive|QtCore.Qt.MatchExactly)',
    '    if r:',
    '        t.scrollTo(r[0]); g = t.viewport().mapToGlobal(t.visualRect(r[0]).center())',
    '        if g.x() > 0 and g.y() > 0: hit = (g.x(), g.y()); break',
    'say("HIT %s" % ("%d %d" % hit if hit else "none"))'
  ].join('\n'));
  await sl(2000);
  const hit = /HIT (\d+) (\d+)/.exec(await grab(p, 'HIT'));
  if (!hit) { console.log('tree item not reachable'); await b.close(); process.exit(0); }
  await p.mouse.click(+hit[1], +hit[2]);
  await sl(2500);                                   // let the 150 ms enablement timer run

  await run(p, [
    'import sys',
    'import FreeCADGui as Gui',
    'from PySide6 import QtWidgets',
    'def say(m): sys.__stderr__.write(m+"\\n"); sys.__stderr__.flush()',
    'sel = [o.Name for o in Gui.Selection.getSelection()]',
    'fw = QtWidgets.QApplication.focusWidget()',
    'try: act = Gui.Command.get("Std_Delete").isActive()',
    'except Exception as e: act = "EXC %s" % str(e)[:40]',
    'say("STATE sel=%s focus=%s Std_Delete_active=%s" % (sel, fw.__class__.__name__ if fw else None, act))'
  ].join('\n'));
  await sl(2500);
  console.log(await grab(p, 'STATE'));

  await p.keyboard.press('Delete');
  await sl(3500);
  const evs = ((await readLog(p)).match(/EV t=\d+ key=\S+ on=\S+/g) || []);
  console.log('Qt key events during the press: ' + (evs.length ? evs.slice(-6).join(' | ') : 'NONE'));
  await run(p, 'import sys, FreeCAD as App\nsys.__stderr__.write("AFTER objs=%s\\n" % [o.Name for o in App.getDocument("DelKey3").Objects])\nsys.__stderr__.flush()\n');
  await sl(2500);
  console.log(await grab(p, 'AFTER'));
  await b.close().catch(()=>{}); process.exit(0);
})().catch((e)=>{console.log('DRIVER '+String(e).slice(0,200));process.exit(0);});
