// Drive the real GUI: click toolbar buttons and menu items at their actual screen
// coordinates and assert on what the application did. Every other harness calls Python,
// which skips the entire Qt input path -- menus, actions, toolbars. This is the closest
// thing to a person using the app that can be run automatically.
const puppeteer = require('puppeteer-core');
const fs = require('fs');
const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const sl = (ms) => new Promise((r) => setTimeout(r, ms));
const URL = process.argv[2] || 'http://localhost:8792/index.html';

const run = (p, c) => p.evaluate((c) => { const m = window.fcInstance;
  const n = new TextEncoder().encode(c).length + 1; const q = m._malloc(n); m.stringToUTF8(c, q, n);
  (window.fcRunPy || ((mm, pp) => { mm._fcweb_run_python(pp); mm._free(pp); }))(m, q); }, c);
const logOf = (p) => p.evaluate(() => document.getElementById('log').textContent);
const grab = async (p, re) => ((await logOf(p)).match(re) || []);
let tag = 0;
async function ask(p, py, mark, ms = 20000) {          // run python, wait for its marker
  tag++; const m = mark + tag;
  await run(p, py.replace(/@@/g, m));
  const t0 = Date.now();
  while (Date.now() - t0 < ms) {
    const hit = await grab(p, new RegExp(m + ' [^\\n]*', 'g'));
    if (hit.length) return hit[hit.length - 1].slice(m.length + 1);
    await sl(400);
  }
  return null;
}
const PY_STATE = 'import FreeCAD as App, sys\n' +
  'd = App.ActiveDocument\n' +
  'sys.__stderr__.write("@@ docs=%d objs=%d\\n" % (len(App.listDocuments()), len(d.Objects) if d else -1))\n' +
  'sys.__stderr__.flush()\n';
// enumerate whatever popup menu is currently open, with clickable screen coordinates
const PY_POPUP = 'import sys\nfrom PySide6 import QtWidgets, QtCore\n' +
  'w = QtWidgets.QApplication.activePopupWidget()\n' +
  'if w is None:\n' +
  '    sys.__stderr__.write("@@ NOPOPUP\\n")\n' +
  'else:\n' +
  '    n = 0\n' +
  '    for a in w.actions():\n' +
  '        if not a.isVisible() or a.isSeparator() or not a.isEnabled():\n' +
  '            continue\n' +
  '        r = w.actionGeometry(a)\n' +
  '        c = w.mapToGlobal(QtCore.QPoint(r.x() + 20, r.y() + r.height() // 2))\n' +
  '        sys.__stderr__.write("@@ ITEM %s|%d|%d\\n" % (a.text().replace("&", ""), c.x(), c.y()))\n' +
  '        n += 1\n' +
  '    sys.__stderr__.write("@@ POPUP items=%d\\n" % n)\n' +
  'sys.__stderr__.flush()\n';

(async () => {
  const results = [];
  const errs = [];
  const b = await puppeteer.launch({ executablePath: CHROME, headless: false, defaultViewport: null,
    args: ['--no-sandbox', '--use-gl=angle', '--use-angle=metal', '--window-size=1400,900'],
    protocolTimeout: 2400000, userDataDir: '/tmp/fc-guidrive-' + Date.now() });
  const p = (await b.pages())[0];
  p.on('pageerror', (e) => errs.push('PAGEERR ' + String(e.message || e).slice(0, 120)));
  await p.goto(URL, { waitUntil: 'domcontentloaded', timeout: 300000 });
  const t0 = Date.now();
  while (Date.now() - t0 < 400000) { if (await p.evaluate(() => !!(window.fcInstance && window.fcInstance._malloc))) break; await sl(1000); }
  await sl(18000);


  const remap = async () => {
    await ask(p, fs.readFileSync('/tmp/guimap.py', 'utf8').replace(/GUI /g, '@@ '), 'MAP', 40000);
    const txt = await logOf(p);
    const mn = {}, tl = {};
    for (const m of txt.matchAll(/MAP(\d+)\s+MENU '([^']*)' (\d+) (\d+)/g)) mn[m[2]] = [+m[3], +m[4], +m[1]];
    for (const m of txt.matchAll(/MAP(\d+)\s+TOOL '[^']*' '([^']*)' (\d+) (\d+)/g)) tl[m[2]] = [+m[3], +m[4], +m[1]];
    // keep only the newest reading of each label
    return { menus: mn, tools: tl };
  };
  // --- where is everything?
  const map = await ask(p, fs.readFileSync('/tmp/guimap.py', 'utf8').replace(/GUI /g, '@@ '), 'MAP', 40000);
  const full = await logOf(p);
  const menus = {}; const tools = {};
  for (const m of full.matchAll(/MAP\d+\s+MENU '([^']*)' (\d+) (\d+)/g)) menus[m[1]] = [+m[2], +m[3]];
  for (const m of full.matchAll(/MAP\d+\s+TOOL '[^']*' '([^']*)' (\d+) (\d+)/g)) tools[m[1]] = [+m[2], +m[3]];
  results.push('menus found: ' + Object.keys(menus).filter(Boolean).join(',') );
  results.push('toolbar buttons found: ' + Object.keys(tools).filter(Boolean).join(','));

  // --- 1. click the New button on the File toolbar
  let before = await ask(p, PY_STATE, 'ST');
  if (tools['New']) { await p.mouse.click(tools['New'][0], tools['New'][1]); await sl(3500); }
  let after = await ask(p, PY_STATE, 'ST');
  results.push('toolbar New: ' + before + '  ->  ' + after);

  // --- 2. open a menu and click an item in it
  if (menus['View']) {
    await p.mouse.click(menus['View'][0], menus['View'][1]);
    await sl(1800);
    const pop = await ask(p, PY_POPUP, 'POP', 20000);
    const items = [...(await logOf(p)).matchAll(/POP\d+ ITEM ([^|]+)\|(\d+)\|(\d+)/g)].map((m) => [m[1], +m[2], +m[3]]);
    results.push('View menu opened: ' + (pop || 'no response') + '  first items: ' +
      items.slice(0, 5).map((i) => i[0]).join(' / '));
    const fit = items.find((i) => /^Fit all/i.test(i[0])) || items.find((i) => /Std views|Standard views/i.test(i[0]));
    if (fit) { await p.mouse.click(fit[1], fit[2]); await sl(2500); results.push('clicked menu item: ' + fit[0]); }
    else { await p.keyboard.press('Escape'); results.push('clicked menu item: none matched'); }
    await p.keyboard.press('Escape'); await sl(400);
    await p.mouse.click(700, 620); await sl(800);       // clicking away is what closes it
    const stillOpen = await ask(p, 'import sys\nfrom PySide6 import QtWidgets\n' +
      'sys.__stderr__.write("@@ popup=%s\\n" % (QtWidgets.QApplication.activePopupWidget() is not None))\n' +
      'sys.__stderr__.flush()\n', 'POPQ');
    results.push('menus closed: ' + stillOpen);
  }

  // --- 3. make an object, then undo and redo it FROM THE TOOLBAR
  await run(p, 'import FreeCAD as App\nd=App.ActiveDocument or App.newDocument("G")\n' +
    'd.openTransaction("make box")\nd.addObject("Part::Box","B")\n' +
    'd.commitTransaction()\nd.recompute()\n');
  await sl(3000);          // FreeCAD refreshes action enablement on a 150 ms timer
  const made = await ask(p, PY_STATE, 'ST');
  let fresh = await remap();
  if (fresh.tools['Undo']) { await p.mouse.click(fresh.tools['Undo'][0], fresh.tools['Undo'][1]); await sl(3000); }
  const undone = await ask(p, PY_STATE, 'ST');
  fresh = await remap();
  if (fresh.tools['Redo']) { await p.mouse.click(fresh.tools['Redo'][0], fresh.tools['Redo'][1]); await sl(3000); }
  const redone = await ask(p, PY_STATE, 'ST');
  results.push('made: ' + made + ' | after toolbar Undo: ' + undone + ' | after toolbar Redo: ' + redone);

  // --- 4. Fit all from the toolbar, asserting the camera actually moved
  // getCamera() returns a string, so this does not need the pivy/SWIG bindings loaded
  const cam = async () => (await ask(p, 'import FreeCADGui as Gui, sys\n' +
    'try:\n' +
    '    sys.__stderr__.write("@@ %s\\n" % Gui.ActiveDocument.ActiveView.getCamera().replace(chr(10)," ")[:90])\n' +
    'except Exception as e:\n' +
    '    sys.__stderr__.write("@@ ERR %s\\n" % e)\n' +
    'sys.__stderr__.flush()\n', 'CAM'));
  const c0 = await cam();
  fresh = await remap();
  if (fresh.tools['Fit all']) { await p.mouse.click(fresh.tools['Fit all'][0], fresh.tools['Fit all'][1]); await sl(3000); }
  const c1 = await cam();
  results.push('toolbar Fit all: camera ' + (c0 !== c1 ? 'MOVED' : 'unchanged') + ' (' + c0 + ' -> ' + c1 + ')');

  results.push('page errors: ' + (errs.length ? errs.join(' | ') : 'none'));
  console.log(results.join('\n'));
  await p.screenshot({ path: '/tmp/guidrive.png' });
  await b.close().catch(() => {}); process.exit(0);
})().catch((e) => { console.log('DRIVER ' + String(e).slice(0, 250)); process.exit(1); });
