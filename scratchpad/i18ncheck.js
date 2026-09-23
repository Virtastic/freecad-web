// Do FreeCAD's own translations arrive, and only the chosen language's?
//
// The Reddit report (2026-09-21): picking a language translated a few Python workbenches
// and left FreeCAD itself in English, because the wasm build compiled no .ts files. The
// image now carries them under i18n/ and the page registers them lazily. This switches to
// German through Gui.setLocale -- the same Translator::activateLanguage the Preferences
// page calls -- then reads the real menu bar, and counts which .qm files crossed the wire.
//
//   node scratchpad/i18ncheck.js [url]
const puppeteer = require('puppeteer-core');
const sl = (ms) => new Promise((r) => setTimeout(r, ms));
const NL = String.fromCharCode(10);
const URL = process.argv[2] || 'http://127.0.0.1:8792/freecad-gui.html';
let fails = 0;
const ok = (c, m) => { console.log((c ? '  ok   ' : '  FAIL ') + m); if (!c) fails++; };
const runPy = (p, c) => p.evaluate((c) => { const m = window.fcInstance; const n = new TextEncoder().encode(c).length + 1; const q = m._malloc(n); m.stringToUTF8(c, q, n); window.fcRunPy(m, q); }, c);
const readFile = (p, f) => p.evaluate((f) => { try { return window.fcInstance.FS.readFile(f, { encoding: 'utf8' }); } catch (e) { return null; } }, f);
const MENUS = ['from PySide import QtWidgets', 'import FreeCADGui as Gui, json',
  'mw = Gui.getMainWindow()',
  'out = [a.text() for a in mw.menuBar().actions()]'].join(NL);
(async () => {
  const b = await puppeteer.launch({ executablePath: process.env.CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: true,
    defaultViewport: { width: 1400, height: 900 }, args: ['--no-sandbox', '--use-gl=angle'], protocolTimeout: 900000,
    userDataDir: 'C:/Users/MICHAE~1/AppData/Local/Temp/fc-i18n-' + Date.now() });
  const p = (await b.pages())[0];
  const qm = [];
  p.on('request', (r) => { if (/\/i18n\//.test(r.url())) qm.push(r.url().replace(/^.*\/i18n\//, '')); });
  await p.goto(URL, { waitUntil: 'domcontentloaded', timeout: 300000 });
  const t = Date.now();
  while (Date.now() - t < 420000) { if (await p.evaluate(() => !!window.__fcWorkReady && !!(window.fcInstance && window.fcInstance._malloc))) break; await sl(1500); }
  await sl(8000);
  const before = qm.slice();
  // English is the active language at boot, so Translator loads *_en.qm (Help ships one),
  // exactly as desktop does. Anything else at boot would be a language nobody chose.
  ok(/^index\.json/.test(before[0]) && before.slice(1).every((f) => /_en\.qm/.test(f)),
     'boot fetched the manifest and English only: ' + JSON.stringify(before));

  await runPy(p, MENUS + NL + 'loc = Gui.supportedLocales()' + NL +
    'open("/tmp/i18n0.json","w").write(json.dumps({"menus": out, "n": len(loc), "de": loc.get("German")}))');
  await sl(4000);
  const m0 = JSON.parse(await readFile(p, '/tmp/i18n0.json') || '{}');
  console.log('  English menus: ' + JSON.stringify(m0.menus));
  ok(m0.de === 'de' && m0.n >= 40, 'German is offered (' + m0.n + ' languages)');

  await runPy(p, 'import FreeCADGui as Gui' + NL + 'Gui.setLocale("German")' + NL + 'Gui.updateGui()');
  await sl(8000);
  await runPy(p, MENUS + NL + 'open("/tmp/i18n1.json","w").write(json.dumps({"menus": out}))');
  await sl(4000);
  const m1 = JSON.parse(await readFile(p, '/tmp/i18n1.json') || '{}');
  console.log('  German menus:  ' + JSON.stringify(m1.menus));
  const got = qm.slice(before.length);
  console.log('  fetched after switching: ' + got.length + ' files, e.g. ' + JSON.stringify(got.slice(0, 6)));
  ok((m1.menus || []).some((s) => /Datei/.test(s)), 'the File menu reads "Datei"');
  ok((m1.menus || []).some((s) => /Bearbeiten/.test(s)), 'the Edit menu reads "Bearbeiten"');
  ok(got.length > 5 && got.every((f) => /_de\.qm/.test(f)), 'only German files were fetched');
  await p.screenshot({ path: 'C:/tmp/i18ncheck.png' });
  await b.close();
  console.log(fails ? NL + fails + ' FAILED' : NL + 'all passed: FreeCAD speaks German');
  process.exit(fails ? 1 : 0);
})();
