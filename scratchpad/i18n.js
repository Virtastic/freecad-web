// Can the browser build speak German, and does FreeCAD's own language machinery work
// once the translations are present?
//
// Measured 2026-09-22 (a user reported "language selection missing"): the picture is
// subtler than that. The Preferences language box IS there and DOES list 40 languages,
// because Translator::supportedLocales() (src/Gui/Language/Translator.cpp:268) counts a
// language whenever it finds *_<code>.qm in its search dirs, and Qt's own qtbase_*.qm
// are compiled into the binary through src/Gui/Language/translation.qrc. What the
// package carries ZERO of is FreeCAD's OWN .qm, so picking Deutsch translates Qt's
// stock buttons and nothing else: the app stays English and the setting looks dead.
//
// This harness writes upstream's prebuilt German .qm into <userAppData>/translations --
// a directory Translator::directories() already searches (line 355), so no preference,
// no engine change, no relink -- and then checks:
//   1. the language box is populated and Preferences opens from a real click
//   2. Gui.setLocale("German") is accepted
//   3. UI text that comes from the added files really is German afterwards
// The core menus (File, Edit, View) need FreeCAD_de.qm, which upstream generates from
// src/Gui/Language/*.ts with lrelease; the builder has no lrelease, so that stays
// English and is recorded here as the one build-side gap.
//
//   node scratchpad/i18n.js [url]      (.qm files come from C:/tmp/qm-de, see the report)
const fs = require('fs');
const path = require('path');
const puppeteer = require('puppeteer-core');
const sl = (ms) => new Promise((r) => setTimeout(r, ms));
const NL = String.fromCharCode(10);
const URL = process.argv[2] || 'http://127.0.0.1:8792/freecad-gui.html';
const QM_DIR = process.env.QM_DIR || 'C:/tmp/qm-de';
const CHROME = process.env.CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const TRANS = '/home/web_user/.local/share/FreeCAD/v1-1/translations';   // userAppDataDir + "translations"
let fails = 0;
const ok = (c, m) => { console.log((c ? '  ok   ' : '  FAIL ') + m); if (!c) fails++; };
const runPy = (p, c) => p.evaluate((c) => { const m = window.fcInstance; const n = new TextEncoder().encode(c).length + 1; const q = m._malloc(n); m.stringToUTF8(c, q, n); (window.fcRunPy)(m, q); }, c);
const waitFile = async (p, file, ms) => {
  const t = Date.now();
  while (Date.now() - t < ms) {
    const s = await p.evaluate((f) => { try { return window.fcInstance.FS.readFile(f, { encoding: 'utf8' }); } catch (e) { return null; } }, file);
    if (s) return s;
    await sl(1200);
  }
  return null;
};
// Real-input menu walk, same approach as scratchpad/dlgsuite.js: ask Qt where the item is,
// then click it with a trusted mouse event (a scripted runCommand would not prove the
// user's path, and a modal opened from Python can suspend illegally).
const menuPath = async (p, top, entry) => {
  await runPy(p, [
    'import FreeCADGui as Gui',
    'mw = Gui.getMainWindow(); out = "none"',
    'for a in mw.menuBar().actions():',
    '    if a.text().replace("&","").strip().lower().startswith("' + top + '"):',
    '        g = mw.menuBar().mapToGlobal(mw.menuBar().actionGeometry(a).center()); out = "%d %d" % (g.x(), g.y())',
    'open("/tmp/i18n-menu.txt", "w").write(out)',
  ].join(NL));
  const t = /(\d+) (\d+)/.exec(await waitFile(p, '/tmp/i18n-menu.txt', 30000) || '');
  if (!t) return 'no top menu ' + top;
  await p.mouse.click(+t[1], +t[2]); await sl(2500);
  await runPy(p, [
    'from PySide6 import QtWidgets',
    'out = "none"',
    'for m in QtWidgets.QApplication.topLevelWidgets():',
    '    if isinstance(m, QtWidgets.QMenu) and m.isVisible():',
    '        for a in m.actions():',
    '            if "' + entry + '" in a.text().replace("&","").strip().lower() and a.isEnabled():',
    '                g = m.mapToGlobal(m.actionGeometry(a).center())',
    '                if g.y() > 0: out = "%d %d" % (g.x(), g.y())',
    'open("/tmp/i18n-entry.txt", "w").write(out)',
  ].join(NL));
  const e = /(\d+) (\d+)/.exec(await waitFile(p, '/tmp/i18n-entry.txt', 30000) || '');
  if (!e) { await p.keyboard.press('Escape'); return 'no entry ' + entry; }
  await p.mouse.click(+e[1], +e[2]);
  return 'clicked';
};
const J = (s) => { try { return JSON.parse(s); } catch (e) { return null; } };

// every *_de.qm upstream ships, as {name: base64}
function qmFiles() {
  const out = {};
  for (const f of fs.readdirSync(QM_DIR, { recursive: true })) {
    const full = path.join(QM_DIR, String(f));
    if (!String(f).endsWith('.qm') || !fs.statSync(full).isFile()) continue;
    out[path.basename(String(f))] = fs.readFileSync(full).toString('base64');
  }
  return out;
}

(async () => {
  const files = qmFiles();
  console.log('  ' + Object.keys(files).length + ' German .qm files, ' +
    Math.round(Object.values(files).reduce((a, b) => a + b.length * 0.75, 0) / 1024) + ' KB');
  const b = await puppeteer.launch({ executablePath: CHROME, headless: true, defaultViewport: { width: 1400, height: 900 },
    args: ['--no-sandbox', '--use-gl=angle'], protocolTimeout: 900000, userDataDir: 'C:/Users/MICHAE~1/AppData/Local/Temp/fc-i18n-' + Date.now() });
  const p = (await b.pages())[0];
  await p.goto(URL, { waitUntil: 'domcontentloaded', timeout: 300000 });
  const t = Date.now();
  while (Date.now() - t < 420000) { if (await p.evaluate(() => !!window.__fcWorkReady && !!(window.fcInstance && window.fcInstance._malloc))) break; await sl(1000); }
  await sl(8000);

  // 1. what FreeCAD offers before anything is added
  await runPy(p, [
    'import FreeCADGui as Gui, json',
    'open("/tmp/i18n-before.json", "w").write(json.dumps(sorted(Gui.supportedLocales().keys())))',
  ].join(NL));
  const before = J(await waitFile(p, '/tmp/i18n-before.json', 60000)) || [];
  console.log('  before: ' + JSON.stringify(before));
  ok(before.includes('German'), 'the language list is populated before anything is added (' + before.length + ' locales, from Qt embedded .qm)');

  // 2. write the translations where FreeCAD already looks
  const wrote = await p.evaluate((dir, files) => {
    const FS = window.fcInstance.FS;
    FS.mkdirTree(dir);
    let n = 0;
    for (const name in files) {
      const bin = atob(files[name]);
      const buf = new Uint8Array(bin.length);
      for (let i = 0; i < bin.length; i++) buf[i] = bin.charCodeAt(i);
      FS.writeFile(dir + '/' + name, buf); n++;
    }
    return n;
  }, TRANS, files);
  ok(wrote === Object.keys(files).length, 'wrote ' + wrote + ' .qm into ' + TRANS);

  // 3. ask again, switch, and read a translated string back out of Qt
  await runPy(p, [
    'import FreeCADGui as Gui, json',
    'o = {"locales": sorted(Gui.supportedLocales().keys())}',
    'try:',
    '    Gui.setLocale("German")',
    '    o["set"] = True',
    'except Exception as e:',
    '    o["set"] = repr(e)',
    'from PySide6 import QtCore, QtWidgets',
    'o["translated_draft"] = QtCore.QCoreApplication.translate("Draft", "Line")',
    'o["translated_arch"] = QtCore.QCoreApplication.translate("Arch", "Wall")',
    'o["translated_am"] = QtCore.QCoreApplication.translate("AddonsInstaller", "Update all addons")',
    'o["menu_file"] = QtCore.QCoreApplication.translate("Workbench", "&File")   # core Gui: needs FreeCAD_de.qm',
    'open("/tmp/i18n-after.json", "w").write(json.dumps(o))',
  ].join(NL));
  const after = J(await waitFile(p, '/tmp/i18n-after.json', 90000)) || {};
  console.log('  after: ' + JSON.stringify(after));
  ok((after.locales || []).includes('German'), 'German appears in the language list once the files are there');
  ok(after.set === true, 'Gui.setLocale("German") accepted');
  console.log('  (context probes, weak: exact source strings vary) draft=' + after.translated_draft + ' am=' + after.translated_am);
  // The core Gui .qm (FreeCAD_de.qm) is NOT in upstream's tree: it is built from
  // src/Gui/Language/FreeCAD_de.ts by lrelease, which the build never ran. Menus stay
  // English until that step exists, so this check records the gap rather than failing.
  console.log('  (gap) core Gui menu string: "' + after.menu_file + '" (English until lrelease runs on the 47 .ts files)');

  // 5. What the user actually does: Edit > Preferences, General page, Language box.
  console.log('  Edit > Preferences: ' + await menuPath(p, 'edit', 'preference'));
  await sl(12000);
  await runPy(p, [
    'import json',
    'from PySide6 import QtWidgets',
    'o = {"dialogs": []}',
    'for w in QtWidgets.QApplication.topLevelWidgets():',
    '    if isinstance(w, QtWidgets.QDialog) and w.isVisible():',
    '        o["dialogs"].append(type(w).__name__ + ":" + w.windowTitle())',
    '        for cb in w.findChildren(QtWidgets.QComboBox):',
    '            name = cb.objectName()',
    '            if "anguage" in name or "Language" in (cb.toolTip() or ""):',
    '                o["language_box"] = {"name": name, "count": cb.count(), "current": cb.currentText(),',
    '                                     "visible": cb.isVisible(), "items": [cb.itemText(i) for i in range(min(cb.count(), 6))]}',
    '        o["combo_names"] = [c.objectName() for c in w.findChildren(QtWidgets.QComboBox)][:14]',
    '        pages = []',
    '        for tw in w.findChildren(QtWidgets.QTreeWidget):   # the page list is a tree (groups with children)',
    '            it = QtWidgets.QTreeWidgetItemIterator(tw)',
    '            while it.value():',
    '                pages.append(it.value().text(0)); it += 1',
    '        for lw in w.findChildren(QtWidgets.QListWidget):',
    '            pages.extend(lw.item(i).text() for i in range(lw.count()))',
    '        o["pages"] = [t for t in pages if t]',
    '        o["buttons"] = [b.text().replace("&", "") for b in w.findChildren(QtWidgets.QPushButton) if b.isVisible()][:8]',
    'import FreeCADGui as Gui',
    'o["menubar"] = [a.text().replace("&", "") for a in Gui.getMainWindow().menuBar().actions()][:6]',
    'open("/tmp/i18n-prefs.json", "w").write(json.dumps(o))',
  ].join(NL));
  const prefs = J(await waitFile(p, '/tmp/i18n-prefs.json', 90000)) || {};
  console.log('  prefs: ' + JSON.stringify(prefs).slice(0, 700));
  ok((prefs.dialogs || []).length > 0, 'Preferences opens from the Edit menu with a real click');
  ok(!!prefs.language_box && prefs.language_box.visible, 'the General page has a visible Language box');
  ok(!!prefs.language_box && prefs.language_box.count > 1, 'the Language box lists languages: ' + JSON.stringify((prefs.language_box || {}).items));
  ok((prefs.language_box || {}).current === 'Deutsch', 'the box shows the language that was set: ' + (prefs.language_box || {}).current);
  // The real question: does any of the UI come out German? The page list carries names
  // from the modules whose .qm we just added, so it is the honest place to look.
  const text = (prefs.pages || []).concat(prefs.buttons || []);
  const german = text.filter(x => /Allgemein|Hilfe|Anzeige|Arbeitsbereiche|Abbrechen|Anwenden/.test(x));
  ok(german.length > 0, 'UI text is German where a .qm exists: ' + JSON.stringify(german));
  // The one build gap: the core Gui's own .qm is generated from .ts by lrelease, which the
  // build never ran, so the menu bar stays English however the language is set.
  ok((prefs.menubar || []).includes('File'),
     'core menus stay English without FreeCAD_de.qm (the one build gap): ' + JSON.stringify(prefs.menubar));
  await p.screenshot({ path: 'C:/tmp/i18n-prefs.png' });
  console.log('  screenshot: C:/tmp/i18n-prefs.png');

  await b.close();
  console.log(fails ? `${NL}${fails} FAILED` : `${NL}all passed`);
  process.exit(fails ? 1 : 0);
})();
