// The language switch the way a user makes it: Edit > Preferences with real clicks, pick
// Deutsch in General's language box, OK, then read the real menu bar. i18ncheck.js proves
// the files and Gui.setLocale; this proves the Preferences path a person actually takes,
// and counts which .qm files crossed the wire (German only, plus the English set at boot).
// The Start page's own language box keeps showing the old language afterwards; so does
// desktop (Start/Gui/GeneralSettingsWidget.cpp sets its index only at construction).
//
//   node scratchpad/i18nclick.js [url]     (default: production)
const puppeteer = require('puppeteer-core');
const sl = (ms) => new Promise((r) => setTimeout(r, ms));
const URL = process.argv[2] || 'https://freecad.virtastic.app/';
const CHROME = process.env.CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe';
let fails = 0;
const ok = (c, m) => { console.log((c ? '  ok   ' : '  FAIL ') + m); if (!c) fails++; };

const run = (p, c) => p.evaluate((c) => { const m = window.fcInstance;
  const n = new TextEncoder().encode(c).length + 1; const q = m._malloc(n); m.stringToUTF8(c, q, n);
  window.fcRunPy(m, q); }, c);
let tag = 0;
// run python that writes "@@ <payload>" to stderr; resend while the interpreter is busy
async function ask(p, py, ms = 30000) {
  const m = 'Q' + (++tag) + 'Z';
  const t0 = Date.now(); let sent = 0;
  while (Date.now() - t0 < ms) {
    if (Date.now() - sent > 5000) { await run(p, py.replace(/@@/g, m)); sent = Date.now(); }
    const hit = (await p.evaluate(() => document.getElementById('log').textContent)).match(new RegExp(m + ' ([^\\n]*)'));
    if (hit) return hit[1];
    await sl(400);
  }
  return null;
}
const HEAD = 'import sys, json\nfrom PySide6 import QtWidgets, QtCore\nimport FreeCADGui as Gui\n' +
  'def c(w, r=None):\n    r = r or w.rect()\n    g = w.mapToGlobal(QtCore.QPoint(r.x() + r.width() // 2, r.y() + r.height() // 2))\n    return [g.x(), g.y()]\n' +
  'def say(o):\n    sys.__stderr__.write("@@ " + json.dumps(o) + "\\n"); sys.__stderr__.flush()\n';
const MENUBAR = HEAD + 'mb = Gui.getMainWindow().menuBar()\n' +
  'say({a.text().replace("&", ""): c(mb, mb.actionGeometry(a)) for a in mb.actions() if a.isVisible()})\n';
const POPUP = HEAD + 'w = QtWidgets.QApplication.activePopupWidget()\n' +
  'say(None if w is None else {a.text().replace("&", ""): c(w, w.actionGeometry(a)) for a in w.actions() if a.isVisible() and not a.isSeparator()})\n';
// the language box: the combo on the open Preferences dialog that lists Deutsch
const PREFS = HEAD + 'd = [w for w in QtWidgets.QApplication.topLevelWidgets() if w.isVisible() and isinstance(w, QtWidgets.QDialog)]\n' +
  'o = {"dialogs": [x.windowTitle() for x in d]}\n' +
  'for x in d:\n    for cb in x.findChildren(QtWidgets.QComboBox):\n' +
  '        items = [cb.itemText(i) for i in range(cb.count())]\n' +
  '        if cb.isVisible() and any("Deutsch" in t for t in items):\n' +
  '            o["combo"] = c(cb); o["current"] = cb.currentText(); o["name"] = cb.objectName()\n' +
  '    for bb in x.findChildren(QtWidgets.QDialogButtonBox):\n' +
  '        b = bb.button(QtWidgets.QDialogButtonBox.Ok)\n' +
  '        if b and b.isVisible(): o["okbtn"] = c(b)\n' +
  'say(o)\n';
const COMBOLIST = HEAD + 'w = QtWidgets.QApplication.activePopupWidget()\n' +
  'v = w.findChild(QtWidgets.QListView) if w else None\n' +
  'if v is None:\n    say(None)\nelse:\n    m = v.model(); hit = None\n' +
  '    for i in range(m.rowCount()):\n        ix = m.index(i, 0)\n' +
  '        if "Deutsch" in str(m.data(ix)):\n            v.scrollTo(ix); hit = c(v.viewport(), v.visualRect(ix))\n' +
  '    say({"deutsch": hit})\n';

(async () => {
  const b = await puppeteer.launch({ executablePath: CHROME, headless: false, defaultViewport: null,
    args: ['--no-sandbox', '--window-size=1400,950'], protocolTimeout: 900000,
    userDataDir: 'C:/Users/MICHAE~1/AppData/Local/Temp/fc-i18nclick-' + Date.now() });
  const p = (await b.pages())[0];
  const qm = []; const errs = [];
  p.on('request', (r) => { if (/\/i18n\/[^?]+\.qm/.test(r.url())) qm.push(r.url().replace(/^.*\/i18n\//, '').replace(/\?.*/, '')); });
  p.on('pageerror', (e) => errs.push(String(e.message || e).slice(0, 160)));
  await p.goto(URL, { waitUntil: 'domcontentloaded', timeout: 300000 });
  const t0 = Date.now();
  while (Date.now() - t0 < 420000) {
    if (await p.evaluate(() => !!window.__fcWorkReady && !!document.querySelector('#load.hide'))) break;
    await sl(2000);
  }
  await sl(12000);
  await p.keyboard.press('Escape'); await sl(500);        // a notification popup, if any
  // Qt's global coordinates ARE page coordinates, our 40 px bar included (measured on
  // production 2026-09-23: Edit at Qt y=52 opened with a click at page y=52, not y=92).
  const click = async (xy) => { await p.mouse.click(xy[0], xy[1]); };
  console.log('booted in ' + Math.round((Date.now() - t0) / 1000) + ' s');
  const bootQm = qm.slice();
  ok(bootQm.every((f) => /_en\.qm$/.test(f)), 'boot fetched English .qm only: ' + JSON.stringify(bootQm));

  const mb = JSON.parse(await ask(p, MENUBAR) || 'null');
  ok(mb && mb.Edit, 'menu bar before: ' + JSON.stringify(mb && Object.keys(mb)));
  await click(mb.Edit); await sl(1500);
  const edit = JSON.parse(await ask(p, POPUP) || 'null');
  const prefKey = edit && Object.keys(edit).find((k) => /^Preferences/.test(k));
  ok(!!prefKey, 'a real click opened Edit, which lists ' + prefKey);
  await click(edit[prefKey]); await sl(6000);
  const pr = JSON.parse(await ask(p, PREFS) || 'null');
  ok(pr && pr.combo && pr.okbtn, 'Preferences opened with a language box (' + (pr && pr.name) + ', now ' + (pr && pr.current) + ')');
  await click(pr.combo); await sl(1500);
  const lst = JSON.parse(await ask(p, COMBOLIST) || 'null');
  ok(lst && lst.deutsch, 'the language list is open and shows Deutsch');
  await sl(800);
  const lst2 = JSON.parse(await ask(p, COMBOLIST) || 'null');   // after scrollTo settled
  await click((lst2 && lst2.deutsch) || lst.deutsch); await sl(1500);
  const pr2 = JSON.parse(await ask(p, PREFS) || 'null');
  ok(pr2 && /Deutsch/.test(pr2.current), 'the box now reads ' + (pr2 && pr2.current));
  await click(pr2.okbtn); await sl(12000);

  const mb2 = JSON.parse(await ask(p, MENUBAR) || 'null');
  const names = mb2 ? Object.keys(mb2) : [];
  ok(names.includes('Datei') && names.includes('Bearbeiten'), 'menu bar after: ' + JSON.stringify(names));
  const after = qm.slice(bootQm.length);
  ok(after.length > 0 && after.every((f) => /_de\.qm$/.test(f)), after.length + ' .qm fetched after the switch, all German: ' + JSON.stringify(after.slice(0, 6)));
  ok(errs.length === 0, 'page errors: ' + JSON.stringify(errs.slice(0, 3)));
  await p.screenshot({ path: process.env.SHOT || 'C:/Users/MICHAE~1/AppData/Local/Temp/i18nclick.png' });
  await b.close();
  console.log(fails ? fails + ' FAILED' : 'ALL PASS');
  process.exit(fails ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(2); });
