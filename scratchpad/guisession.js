// A modelling session driven entirely through the GUI: switch to the Model tree, select
// an object by clicking it, watch the property editor fill, and change workbench from the
// selector. These are the surfaces a person touches constantly and that calling Python
// never exercises.
const puppeteer = require('puppeteer-core');
const fs = require('fs');
const CHROME = process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';  // set CHROME_PATH to run off macOS
const sl = (ms) => new Promise((r) => setTimeout(r, ms));
const URL = process.argv[2] || 'http://localhost:8792/index.html';
const run = (p, c) => p.evaluate((c) => { const m = window.fcInstance;
  const n = new TextEncoder().encode(c).length + 1; const q = m._malloc(n); m.stringToUTF8(c, q, n);
  (window.fcRunPy || ((mm, pp) => { mm._fcweb_run_python(pp); mm._free(pp); }))(m, q); }, c);
const logOf = (p) => p.evaluate(() => document.getElementById('log').textContent);
const last = async (p, re) => ((await logOf(p)).match(re) || []).pop() || '(none)';
const all = async (p, re) => [...(await logOf(p)).matchAll(re)];

(async () => {
  const out = []; const errs = [];
  const b = await puppeteer.launch({ executablePath: CHROME, headless: false, defaultViewport: null,
    args: ['--no-sandbox', '--use-gl=angle', '--use-angle=metal', '--window-size=1400,900'],
    protocolTimeout: 2400000, userDataDir: '/tmp/fc-guisession-' + Date.now() });
  const p = (await b.pages())[0];
  p.on('pageerror', (e) => errs.push(String(e.message || e).slice(0, 120)));
  await p.goto(URL, { waitUntil: 'domcontentloaded', timeout: 300000 });
  const t0 = Date.now();
  while (Date.now() - t0 < 400000) { if (await p.evaluate(() => !!(window.fcInstance && window.fcInstance._malloc))) break; await sl(1000); }
  await sl(18000);

  // something to look at
  await run(p, 'import FreeCAD as App, FreeCADGui as Gui\nd=App.newDocument("Session")\n' +
    'b=d.addObject("Part::Box","MyBox")\nd.recompute()\nGui.updateGui()\n');
  await sl(3000);

  const mapPanels = async () => { await run(p, fs.readFileSync('/tmp/gui_panels.py', 'utf8')); await sl(2500); };
  await mapPanels();
  const tabs = (await all(p, /GP TAB ([^|]+)\|(\d+)\|(\d+)\|current=(\w+)/g))
    .map((m) => ({ label: m[1], x: +m[2], y: +m[3], current: m[4] === 'True' }));
  out.push('panel tabs: ' + tabs.map((t) => t.label + (t.current ? '*' : '')).join(', '));

  // 1. click the Model tab so the tree is on screen
  const model = tabs.filter((t) => t.label === 'Model').pop();
  if (model) { await p.mouse.click(model.x, model.y); await sl(2500); }
  await mapPanels();
  const items = (await all(p, /GP TREEITEM ([^|]+)\|(\d+)\|(\d+)/g)).map((m) => ({ t: m[1], x: +m[2], y: +m[3] }));
  out.push('tree items on screen after clicking Model: ' + (items.length
    ? items.slice(-6).map((i) => i.t).join(', ') : 'NONE'));

  // 2. click the object in the tree and see whether FreeCAD selects it
  const box = items.filter((i) => /MyBox/.test(i.t)).pop() || items[items.length - 1];
  let selected = '(no item to click)';
  if (box) {
    await p.mouse.click(box.x, box.y);
    await sl(2500);
    await run(p, 'import FreeCADGui as Gui, sys\ns=Gui.Selection.getSelection()\n' +
      'sys.__stderr__.write("SEL n=%d names=%s\\n" % (len(s), ",".join(o.Name for o in s)))\nsys.__stderr__.flush()\n');
    await sl(1800);
    selected = await last(p, /SEL [^\n]*/g);
  }
  out.push('clicked tree item ' + (box ? '"' + box.t + '"' : '-') + ' -> ' + selected);

  // 3. does the property editor fill in response to that selection?
  await mapPanels();
  out.push('property editor: ' + await last(p, /GP PROPROWS [^\n]*/g));

  // 4. change workbench from the selector, the way a person switches tools
  await run(p, 'import sys\nfrom PySide6 import QtWidgets, QtCore\nimport FreeCADGui as Gui\n' +
    'mw=Gui.getMainWindow()\n' +
    'for c in mw.findChildren(QtWidgets.QComboBox):\n' +
    '    if c.isVisible() and c.count()>3:\n' +
    '        p=c.mapToGlobal(QtCore.QPoint(c.width()//2,c.height()//2))\n' +
    '        sys.__stderr__.write("WB %d %d %s\\n" % (p.x(),p.y(),c.currentText()))\n' +
    '        break\nsys.__stderr__.flush()\n');
  await sl(1800);
  const wb = /WB (\d+) (\d+) (.+)/.exec(await last(p, /WB \d+[^\n]*/g));
  let wbResult = '(selector not found)';
  if (wb) {
    const before = wb[3].trim();
    await p.mouse.click(+wb[1], +wb[2]);
    await sl(2000);
    // the popup is a view of the combo's list; enumerate and click "Part"
    await run(p, 'import sys\nfrom PySide6 import QtWidgets, QtCore\n' +
      'w=QtWidgets.QApplication.activePopupWidget()\n' +
      'if w is None:\n' +
      '    sys.__stderr__.write("WBPOP none\\n")\n' +
      'else:\n' +
      '    v=w.findChild(QtWidgets.QAbstractItemView) or w\n' +
      '    m=getattr(v,"model",lambda:None)()\n' +
      '    if m:\n' +
      '        for r in range(m.rowCount()):\n' +
      '            i=m.index(r,0); rect=v.visualRect(i)\n' +
      '            if rect.isValid() and v.viewport().rect().intersects(rect):\n' +
      '                c=v.viewport().mapToGlobal(rect.center())\n' +
      '                sys.__stderr__.write("WBITEM %s|%d|%d\\n" % (m.data(i), c.x(), c.y()))\n' +
      'sys.__stderr__.flush()\n');
    await sl(1800);
    const wbitems = (await all(p, /WBITEM ([^|]+)\|(\d+)\|(\d+)/g)).map((m) => ({ t: m[1], x: +m[2], y: +m[3] }));
    const target = wbitems.filter((i) => i.t.trim() === 'Part').pop() ||
                   wbitems.filter((i) => i.t.trim() === 'Draft').pop();
    if (target) { await p.mouse.click(target.x, target.y); await sl(6000); }
    else { await p.keyboard.press('Escape'); }
    await run(p, 'import sys, FreeCADGui as Gui\n' +
      'sys.__stderr__.write("WBNOW %s\\n" % Gui.activeWorkbench().name())\nsys.__stderr__.flush()\n');
    await sl(1800);
    wbResult = before + ' -> ' + (await last(p, /WBNOW [^\n]*/g)).replace('WBNOW ', '') +
      '  (popup listed ' + wbitems.length + ' workbenches)';
  }
  out.push('workbench selector: ' + wbResult);

  out.push('page errors: ' + (errs.length ? errs.join(' | ') : 'none'));
  console.log(out.join('\n'));
  await p.screenshot({ path: '/tmp/guisession.png' });
  await b.close().catch(() => {}); process.exit(0);
})().catch((e) => { console.log('DRIVER ' + String(e).slice(0, 250)); process.exit(1); });
