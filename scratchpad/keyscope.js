// Which keyboard input reaches Qt, and when? Evidence so far says keys arrive when a TEXT
// widget has focus but not when the tree does. If true, Delete/undo/most shortcuts are dead
// for users. Test the same keys against both focus states in one run.
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
(async () => {
  const b = await puppeteer.launch({ executablePath: CHROME, headless: false, defaultViewport: null,
    args: ['--no-sandbox','--use-gl=angle','--use-angle=metal','--window-size=1400,900'],
    protocolTimeout: 1800000, userDataDir: '/tmp/fc-keyscope' });
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
    'd = App.newDocument("Scope")',
    'd.addObject("Part::Box","One"); d.recompute()',
    'mw = Gui.getMainWindow()',
    'le = QtWidgets.QLineEdit(mw); le.setObjectName("scopeProbe"); le.setGeometry(60,120,240,32); le.show(); le.raise_()',
    'g = le.mapToGlobal(QtCore.QPoint(120,16)); say("LE %d %d" % (g.x(), g.y()))',
    'class Spy(QtCore.QObject):',
    '    def eventFilter(self, o, e):',
    '        if int(e.type()) == 6:',
    '            try: k = e.key()',
    '            except Exception: k = -1',
    '            say("KEY %s on=%s" % (k, o.__class__.__name__))',
    '        return False',
    'sp = Spy(mw); mw._scopeSpy = sp; QtWidgets.QApplication.instance().installEventFilter(sp)',
    'say("SETUP ok")'
  ].join('\n'));
  await sl(4000);
  const le = /LE (\d+) (\d+)/.exec(await grab(p, 'LE'));

  // A: text widget focused
  await p.mouse.click(+le[1], +le[2]); await sl(1200);
  const before = ((await readLog(p)).match(/KEY \S+ on=\S+/g) || []).length;
  await p.keyboard.press('Delete'); await sl(800);
  await p.keyboard.down(MOD); await p.keyboard.press('KeyZ'); await p.keyboard.up(MOD); await sl(1500);
  const afterText = ((await readLog(p)).match(/KEY \S+ on=\S+/g) || []).slice(before);
  console.log('FOCUS = QLineEdit -> Qt saw: ' + (afterText.length ? afterText.join(' | ') : 'NOTHING'));

  // B: tree focused (click the Model tab then the item)
  await run(p, [
    'import sys',
    'from PySide6 import QtWidgets, QtCore',
    'import FreeCADGui as Gui',
    'def say(m): sys.__stderr__.write(m+"\\n"); sys.__stderr__.flush()',
    'mw = Gui.getMainWindow()',
    'for tb in mw.findChildren(QtWidgets.QTabBar):',
    '    for i in range(tb.count()):',
    '        if tb.tabText(i).strip().lower() == "model":',
    '            g = tb.mapToGlobal(tb.tabRect(i).center()); say("TAB %d %d" % (g.x(), g.y()))'
  ].join('\n'));
  await sl(2000);
  const tab = /TAB (\d+) (\d+)/.exec(await grab(p, 'TAB'));
  if (tab) { await p.mouse.click(+tab[1], +tab[2]); await sl(2000); }
  await run(p, [
    'import sys',
    'from PySide6 import QtWidgets, QtCore',
    'import FreeCADGui as Gui',
    'def say(m): sys.__stderr__.write(m+"\\n"); sys.__stderr__.flush()',
    'mw = Gui.getMainWindow(); hit=None',
    'for t in mw.findChildren(QtWidgets.QTreeWidget):',
    '    if not t.isVisible(): continue',
    '    m = t.model()',
    '    r = m.match(m.index(0,0), QtCore.Qt.DisplayRole, "One", 1, QtCore.Qt.MatchRecursive|QtCore.Qt.MatchExactly)',
    '    if r:',
    '        t.scrollTo(r[0]); g = t.viewport().mapToGlobal(t.visualRect(r[0]).center())',
    '        if g.x()>0 and g.y()>0: hit=(g.x(),g.y()); break',
    'say("HIT %s" % ("%d %d" % hit if hit else "none"))'
  ].join('\n'));
  await sl(2000);
  const hit = /HIT (\d+) (\d+)/.exec(await grab(p, 'HIT'));
  if (hit) {
    await p.mouse.click(+hit[1], +hit[2]); await sl(2000);
    const before2 = ((await readLog(p)).match(/KEY \S+ on=\S+/g) || []).length;
    await p.keyboard.press('Delete'); await sl(800);
    await p.keyboard.down(MOD); await p.keyboard.press('KeyZ'); await p.keyboard.up(MOD); await sl(1500);
    const afterTree = ((await readLog(p)).match(/KEY \S+ on=\S+/g) || []).slice(before2);
    console.log('FOCUS = tree      -> Qt saw: ' + (afterTree.length ? afterTree.join(' | ') : 'NOTHING'));
  }
  console.log('  (Qt::Key_Delete=16777223, Key_Z=90)');
  await b.close().catch(()=>{}); process.exit(0);
})().catch((e)=>{console.log('DRIVER '+String(e).slice(0,200));process.exit(0);});
