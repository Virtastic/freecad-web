// Keyboard shortcuts belong to FreeCAD, not the browser. Reported on launch day: Ctrl+N
// opened a Chrome window instead of a FreeCAD document. This presses REAL keys (puppeteer
// keyboard, trusted events through the shell's forwarder) with the 3D view focused and
// asserts:
//   1. Ctrl+N -> one more FreeCAD document, and NO new browser page/window
//   2. Ctrl+Z after creating a box -> the box is gone (undo reached Qt)
//   3. typing into a FreeCAD text field still works character for character (the guard)
//   node scratchpad/shortcuts.js http://127.0.0.1:8792/freecad-gui.html
const puppeteer = require('puppeteer-core');
const sl = (ms) => new Promise((r) => setTimeout(r, ms));
const NL = String.fromCharCode(10);
const URL = process.argv[2] || 'http://127.0.0.1:8792/freecad-gui.html';
const CHROME = process.env.CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe';
let fails = 0;
const ok = (c, m) => { console.log((c ? '  ok   ' : '  FAIL ') + m); if (!c) fails++; };
const runPy = (p, c) => p.evaluate((c) => { const m = window.fcInstance; const n = new TextEncoder().encode(c).length + 1; const q = m._malloc(n); m.stringToUTF8(c, q, n); (window.fcRunPy)(m, q); }, c);
const marker = async (p, tag, ms) => {
  const t = Date.now();
  while (Date.now() - t < ms) {
    const log = await p.evaluate(() => (document.getElementById('log') || {}).textContent || '');
    const m = log.match(new RegExp('(?:^|\\n)(?:\\{[^}]*\\} )?' + tag + ' ([^\\n]*)'));
    if (m) return m[1];
    await sl(1000);
  }
  return null;
};
const ask = async (p, tag, expr) => {
  await runPy(p, ['import sys, json, FreeCAD as App', 'try:', '    _v = ' + expr, '    sys.__stderr__.write("' + tag + ' " + json.dumps(_v) + "\\n")',
    'except Exception as e:', '    sys.__stderr__.write("' + tag + ' " + json.dumps({"err": repr(e)}) + "\\n")', 'sys.__stderr__.flush()'].join(NL));
  const v = await marker(p, tag, 20000);
  try { return JSON.parse(v); } catch (e) { return null; }
};

(async () => {
  const b = await puppeteer.launch({ executablePath: CHROME, headless: true, defaultViewport: { width: 1400, height: 900 },
    args: ['--no-sandbox', '--use-gl=angle'], protocolTimeout: 1200000, userDataDir: 'C:/Users/MICHAE~1/AppData/Local/Temp/fc-shortcuts-' + Date.now() });
  const p = (await b.pages())[0];
  await p.goto(URL, { waitUntil: 'domcontentloaded', timeout: 300000 });
  const t = Date.now();
  while (Date.now() - t < 420000) { if (await p.evaluate(() => !!window.__fcWorkReady && !!(window.fcInstance && window.fcInstance._malloc))) break; await sl(1000); }
  await sl(12000);
  // Dismiss anything modal and give the 3D view the focus a user would by clicking it.
  await p.keyboard.press('Escape'); await sl(500);
  await p.mouse.click(900, 500); await sl(800);

  const pagesBefore = (await b.pages()).length;
  const docsBefore = await ask(p, 'DOCS0', 'len(App.listDocuments())');
  let tag = 'DOCS0';

  // 1. Ctrl+N
  await p.keyboard.down('Control'); await p.keyboard.press('KeyN'); await p.keyboard.up('Control');
  await sl(2500);
  const docsAfter = await ask(p, 'DOCS1', 'len(App.listDocuments())');
  const pagesAfter = (await b.pages()).length;
  ok(docsAfter === docsBefore + 1, 'Ctrl+N made a FreeCAD document (' + docsBefore + ' -> ' + docsAfter + ')');
  ok(pagesAfter === pagesBefore, 'Ctrl+N opened no browser page (' + pagesBefore + ' -> ' + pagesAfter + ')');

  // 2. Ctrl+Z undoes a real operation in that document
  await runPy(p, ['import FreeCAD as App, FreeCADGui as Gui', 'd = App.ActiveDocument', 'd.addObject("Part::Box", "UndoMe")', 'd.recompute()', 'd.commitTransaction() if False else None'].join(NL));
  await sl(800);
  await runPy(p, ['import FreeCAD as App', 'd=App.ActiveDocument', 'd.openTransaction("box")', 'd.addObject("Part::Box","UndoMe2")', 'd.commitTransaction()', 'd.recompute()'].join(NL));
  await sl(800);
  const n0 = await ask(p, 'OBJ0', 'len(App.ActiveDocument.Objects)');
  await p.mouse.click(900, 500); await sl(300);
  await p.keyboard.down('Control'); await p.keyboard.press('KeyZ'); await p.keyboard.up('Control');
  await sl(1500);
  const n1 = await ask(p, 'OBJ1', 'len(App.ActiveDocument.Objects)');
  ok(n1 === n0 - 1, 'Ctrl+Z undid the last object (' + n0 + ' -> ' + n1 + ')');

  // 3. Typing into a Qt text field is untouched: the Python console.
  await runPy(p, ['import FreeCADGui as Gui', 'from PySide6 import QtWidgets', 'mw = Gui.getMainWindow()',
    'dw = mw.findChild(QtWidgets.QDockWidget, "Python console")', 'dw.show(); dw.raise_()',
    'c = dw.widget(); c.setFocus()', 'import sys; sys.__stderr__.write("CONS %s\\n" % (c.metaObject().className(),)); sys.__stderr__.flush()'].join(NL));
  await marker(p, 'CONS', 10000);
  await sl(800);
  await p.keyboard.type('abc123', { delay: 40 });
  await sl(600);
  const typed = await ask(p, 'TYPED', 'Gui.getMainWindow().findChild(__import__("PySide6").QtWidgets.QPlainTextEdit, "Python console").toPlainText()[-6:] if Gui.getMainWindow().findChild(__import__("PySide6").QtWidgets.QPlainTextEdit, "Python console") else Gui.getMainWindow().findChild(__import__("PySide6").QtWidgets.QDockWidget, "Python console").widget().toPlainText()[-6:]');
  ok(typed === 'abc123', 'typing in a text field is exact: ' + JSON.stringify(typed));

  await b.close();
  console.log(fails ? `${NL}${fails} FAILED` : `${NL}all passed`);
  process.exit(fails ? 1 : 0);
})();
