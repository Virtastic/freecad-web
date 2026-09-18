// SPDX-License-Identifier: LGPL-2.1-or-later
// Copyright (c) Virtastic
//
// README screenshots, taken from the real application rather than mocked up: open each
// document, frame it, and photograph the window. One browser, one file at a time -- each
// of these is a GPU context and a multi-hundred-megabyte document.
//
//   node scratchpad/shots.js <base-url> <out-dir> [name-filter]
//
// Headful on purpose: headless angle/metal breaks Coin's GL hooks, so the viewport comes
// back empty and the shot is a picture of nothing. Same reason the render gates run headful.
//
// Two traps this has already fallen into, both of which produced a confident wrong image:
//   - the readiness marker must be UNIQUE PER SHOT. A fixed marker is still in the log from
//     the previous document, so the wait returns at once and you photograph the old model
//     while the label claims the new one.
//   - FreeCAD's notification list opens OVER the 3D view on any file with blocked add-on
//     imports, and then the screenshot is a wall of warning text.
const fs = require('fs');
const path = require('path');
const puppeteer = require('puppeteer-core');

const URL = process.argv[2] || 'http://127.0.0.1:8899/freecad-gui.html';
const OUT = process.argv[3] || 'docs/images';
const ONLY = process.argv[4] || '';
const CHROME = process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const sl = (ms) => new Promise((r) => setTimeout(r, ms));
const NL = String.fromCharCode(10);

const SHOTS = [
  { file: 'PartDesignExample.FCStd', name: 'partdesign', view: 'axonometric' },
  { file: 'EngineBlock.FCStd', name: 'engineblock', view: 'axonometric' },
  { file: 'BIMExample.FCStd', name: 'bim', view: 'axonometric' },
  { file: 'ArchDetail.FCStd', name: 'archdetail', view: 'axonometric' },
  { file: 'FEMExample.FCStd', name: 'fem', view: 'axonometric' },
  { file: 'AssemblyExample.FCStd', name: 'assembly', view: 'axonometric' },
  { file: 'draft_test_objects.FCStd', name: 'draft', view: 'top' },
  // The two real-world files this port has been tested against all along.
  { url: '900a_GA3DtechProject_v1.0.FCStd', name: 'project-42mb', view: 'axonometric' },
  { url: 'dovahkiin_helm_reforged.stl', name: 'helm-stl', view: 'axonometric' },
];

const runPy = (p, code) => p.evaluate((c) => {
  const m = window.fcInstance;
  const n = new TextEncoder().encode(c).length + 1;
  const q = m._malloc(n);
  m.stringToUTF8(c, q, n);
  (window.fcRunPy || ((mm, pp) => { mm._fcweb_run_python(pp); mm._free(pp); }))(m, q);
}, code);

const logOf = (p) => p.evaluate(() => (document.getElementById('log') || {}).textContent || '');

async function waitFor(p, needle, ms) {
  const t = Date.now();
  while (Date.now() - t < ms) {
    if ((await logOf(p)).includes(needle)) return true;
    await sl(1000);
  }
  return false;
}

const fetchIn = (p, url, dest) => p.evaluate(async (u, d) => {
  const r = await fetch(u, { cache: 'no-store' });
  if (!r.ok) throw new Error('fetch ' + u + ' -> ' + r.status);
  const bytes = new Uint8Array(await r.arrayBuffer());
  window.fcInstance.FS.writeFile(d, bytes);
  return bytes.length;
}, url, dest);

// Anything floating over the window: the notification list, the task panel, a tooltip.
const CLEAN = [
  'from PySide6 import QtCore, QtWidgets',
  'import FreeCADGui as Gui',
  'mw = Gui.getMainWindow()',
  'for w in QtWidgets.QApplication.topLevelWidgets():',
  '    if w is mw or not w.isVisible():',
  '        continue',
  '    w.hide()',
  'for w in mw.findChildren(QtWidgets.QWidget):',
  '    cls = type(w).__name__',
  '    nm = w.objectName() or ""',
  '    if "Notification" in cls or "Notification" in nm or nm in ("Tasks", "OverlayRight"):',
  '        w.hide()',
].join(NL);

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const b = await puppeteer.launch({
    executablePath: CHROME, headless: false, defaultViewport: null,
    args: ['--no-sandbox', '--use-gl=angle', '--enable-features=SharedArrayBuffer',
           '--window-size=1680,1050', '--hide-scrollbars'],
    protocolTimeout: 2400000, userDataDir: '/tmp/fc-shots-' + Date.now(),
  });
  const p = (await b.pages())[0];
  const errs = [];
  p.on('pageerror', (e) => errs.push(String(e).slice(0, 120)));
  await p.goto(URL, { waitUntil: 'domcontentloaded', timeout: 300000 });

  const t0 = Date.now();
  while (Date.now() - t0 < 420000) {
    if (await p.evaluate(() => !!(window.__fcWorkReady))) break;
    await sl(1000);
  }
  await sl(12000);
  // Capture at 2x: these end up in a README, where a soft screenshot reads as a mock-up.
  await p.setViewport({ width: 1460, height: 900, deviceScaleFactor: 2 });
  await sl(6000);

  let n = 0;
  for (const s of SHOTS) {
    if (ONLY && !s.name.includes(ONLY)) continue;
    n += 1;
    const mark = 'SHOT' + n + '-' + s.name;          // unique: see the header
    try {
      if (s.url) {
        const got = await fetchIn(p, s.url, '/home/web_user/' + s.url);
        console.log(s.name + ': fetched ' + Math.round(got / 1048576) + ' MB');
      }
      const src = s.url ? '/home/web_user/' + s.url : s.file;
      await runPy(p, [
        'import sys, os, glob',
        'import FreeCAD as App, FreeCADGui as Gui',
        'for _d in list(App.listDocuments()):',
        '    App.closeDocument(_d)',
        'src = ' + JSON.stringify(src),
        'if not os.path.exists(src):',
        '    hits = glob.glob("/freecad/**/" + os.path.basename(src), recursive=True)',
        '    src = hits[0] if hits else src',
        'try:',
        '    if src.lower().endswith(".stl"):',
        '        import Mesh',
        '        _doc = App.newDocument("Model")',
        '        Mesh.insert(src, _doc.Name)',
        '    else:',
        '        App.openDocument(src)',
        '    App.ActiveDocument.recompute()',
        '    _v = Gui.activeDocument().activeView() if Gui.activeDocument() else None',
        '    _want = "viewTop" if ' + JSON.stringify(s.view) + ' == "top" else "viewAxonometric"',
        '    if _v is not None and hasattr(_v, _want):',
        '        getattr(_v, _want)()',
        '    Gui.SendMsgToActiveView("ViewFit")',
        '    _n = App.ActiveDocument.Name',
        '    _c = len(App.ActiveDocument.Objects)',
        'except Exception as e:',
        '    _n, _c = "FAILED:%r" % (e,), -1',
        // the marker reports WHICH document is on screen, so a wrong one cannot pass silently
        'sys.__stderr__.write("' + mark + ' doc=%s objects=%d\\n" % (_n, _c)); sys.__stderr__.flush()',
      ].join(NL));
      const ok = await waitFor(p, mark, 420000);
      const line = ((await logOf(p)).match(new RegExp(mark + '[^' + NL + ']*')) || [''])[0];
      await p.keyboard.press('Escape');
      await runPy(p, CLEAN);
      await sl(2000);
      await runPy(p, 'import FreeCADGui as Gui' + NL + 'Gui.SendMsgToActiveView("ViewFit")');
      await sl(7000);                      // let the scene settle and a frame present
      const file = path.join(OUT, s.name + '.png');
      await p.screenshot({ path: file });
      const kb = Math.round(fs.statSync(file).size / 1024);
      console.log(s.name + ': ' + (ok ? line.trim() : 'TIMED OUT') + ' -> ' + file + ' (' + kb + ' KB)');
    } catch (e) {
      console.log(s.name + ': FAILED ' + String(e).slice(0, 160));
    }
  }
  console.log('page errors: ' + (errs.length ? errs.slice(0, 5).join(' | ') : 'none'));
  await b.close().catch(() => {});
})();
