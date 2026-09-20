// SPDX-License-Identifier: LGPL-2.1-or-later
// Copyright (c) Virtastic
//
// Two more launch clips, the owner's side of sharing and the MCP page, driven the way a person
// does it: the Share Session command opens Preferences → Sharing, and from there every click is
// a real mouse click, because a modal Preferences dialog PARKS the Python bridge (measured in
// shareshots.js) and nothing can be driven through runPy until it closes.
//
//   node scratchpad/clips-share.js <base-url> <out-dir> [probe]
//
// `probe` takes a screenshot after each step instead of recording, so the click targets in
// CLICK below can be read off real frames. The dialog lays out deterministically at 1600x900.
//
//   share-owner   Edit → Share Session…, Start sharing, the link, Copy, then the Session page
//                 with the visitor who joined in the meantime
//   mcp           the MCP page, Enable assistant, the minted URL and the copy buttons
const fs = require('fs');
const path = require('path');
const puppeteer = require('puppeteer-core');

const URL = process.argv[2] || 'https://freecad.virtastic.app/freecad-gui.html';
const OUT = process.argv[3] || 'launch/assets/clips';
const PROBE = process.argv[4] === 'probe';
const CHROME = process.env.CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const W = 1600, H = 900;
const sl = (ms) => new Promise((r) => setTimeout(r, ms));
const NL = String.fromCharCode(10);

// Click targets inside the Preferences dialog, page coordinates at 1600x900. Read off the
// probe frames; a wrong one clicks empty dialog and the recording shows nothing happening.
const CLICK = {
  start:   [681, 183],   // "Start sharing"
  copy:    [1366, 249],   // "Copy" next to the link
  session: [397, 558],   // "Session" in the left tree, under Sharing
  mcp:     [384, 577],   // "MCP" in the left tree
  enable:  [696, 183],   // "Enable assistant"
  claude:  [877, 249],   // the Claude Code copy button
  edit:    [78, 11],     // the Edit menu in the menu bar
  item:    [144, 557],   // "Share Session…" in that menu
  refresh: [874, 381],   // "Refresh" on the Session page: the page repaints on an action, not on a timer
};

const runPy = (p, code) => p.evaluate((c) => {
  const m = window.fcInstance;
  const n = new TextEncoder().encode(c).length + 1;
  const q = m._malloc(n);
  m.stringToUTF8(c, q, n);
  (window.fcRunPy || ((mm, pp) => { mm._fcweb_run_python(pp); mm._free(pp); }))(m, q);
}, code);
const logOf = (p) => p.evaluate(() => (document.getElementById('log') || {}).textContent || '');
const sess = (p) => p.evaluate(() => {
  const s = window.__fcSession || {};
  return { id: s.id || '', holder: !!s.holder, role: s.role || '', v: s.v, applied: s.applied };
});
const loaderGone = (p) => p.evaluate(() => {
  const el = document.getElementById('load'); return !!el && el.classList.contains('hide');
});
async function until(fn, ms, every) {
  const t = Date.now();
  while (Date.now() - t < ms) {
    try { const v = await fn(); if (v) return v; } catch (e) { /* busy */ }
    await sl(every || 1000);
  }
  return null;
}
const ready = (p, ms) => until(() => p.evaluate(
  () => !!(window.__fcWorkReady && window.fcInstance && window.fcInstance._malloc)), ms);

const CLEAN = [
  'from PySide6 import QtWidgets',
  'import FreeCAD as App, FreeCADGui as Gui',
  'App.ParamGet("User parameter:BaseApp/Preferences/View").SetBool("EnablePreselection", False)',
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
  'for bt in mw.findChildren(QtWidgets.QPushButton):',
  '    if bt.text().strip("&") == "Done" and bt.isVisible():',
  '        bt.click()',
].join(NL);

// A human click: move there first, pause, press.
async function click(p, name) {
  const [x, y] = CLICK[name];
  if (!x && !y) throw new Error('no coordinates for ' + name);
  await p.mouse.move(x - 30, y + 10);
  await sl(250);
  await p.mouse.move(x, y, { steps: 8 });
  await sl(300);
  await p.mouse.click(x, y);
}
let shotN = 0;
const probe = async (p, name) => {
  if (!PROBE) return;
  const f = path.join(OUT, 'probe-' + String(++shotN).padStart(2, '0') + '-' + name + '.png');
  await p.screenshot({ path: f });
  console.log('probe ' + f);
};

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const b = await puppeteer.launch({
    executablePath: CHROME, headless: false, defaultViewport: null,
    args: ['--no-sandbox', '--use-gl=angle', '--enable-features=SharedArrayBuffer',
           '--window-size=' + (W + 16) + ',' + (H + 120), '--hide-scrollbars'],
    protocolTimeout: 2400000, userDataDir: path.join(process.env.TEMP || '/tmp', 'fc-clips-share-' + Date.now()),
  });
  const errs = [];
  const p = (await b.pages())[0];
  p.on('pageerror', (e) => errs.push(String(e).slice(0, 120)));
  await p.setViewport({ width: W, height: H, deviceScaleFactor: 1 });
  await p.goto(URL, { waitUntil: 'domcontentloaded', timeout: 300000 });
  if (!await ready(p, 600000)) { console.log('never Ready'); await b.close(); return; }
  await until(() => loaderGone(p), 120000);
  await sl(3000);

  // The document, copied into the home directory so it reads as the owner's own file.
  await runPy(p, [
    'import sys, glob, shutil',
    'import FreeCAD as App, FreeCADGui as Gui',
    'hits = glob.glob("/freecad/**/PartDesignExample.FCStd", recursive=True)',
    'mine = "/home/web_user/PartDesignExample.FCStd"',
    'shutil.copyfile(hits[0], mine)',
    'App.openDocument(mine)',
    'Gui.activateWorkbench("PartDesignWorkbench")',
    'App.ActiveDocument.recompute()',
    '_v = Gui.activeDocument().activeView(); _v.viewAxonometric(); Gui.SendMsgToActiveView("ViewFit")',
    'App.ParamGet("User parameter:BaseApp/Preferences/FCWeb/Sharing").SetString("DisplayName", "Michael")',
    'sys.__stderr__.write("SHAREDOC %d' + '\\n' + '" % len(App.ActiveDocument.Objects)); sys.__stderr__.flush()',
  ].join(NL));
  const line = await until(async () => { const m = (await logOf(p)).match(/SHAREDOC \d+/); return m ? m[0] : null; }, 300000, 1500);
  console.log('owner: ' + line);
  await p.keyboard.press('Escape');
  await runPy(p, CLEAN);
  await sl(2500);
  await probe(p, 'doc');

  const rec = async (name) => PROBE ? null : p.screencast({ path: path.join(OUT, name + '.webm'), fps: 25 });

  // The menu, the real way: a click on Edit, then on Share Session…. Opening the dialog
  // through runPy instead leaves __fcPyBusy set for the dialog's whole lifetime, the page
  // skips its Python tick, and Start sharing sits on "Starting…" forever (measured).
  if (PROBE) {
    await p.mouse.click(CLICK.edit[0], CLICK.edit[1]);
    await sl(1200);
    await probe(p, 'editmenu');
    await p.keyboard.press('Escape');
    await sl(800);
  }

  // ---- share-owner --------------------------------------------------------------------
  let r = await rec('share-owner');
  await sl(1500);
  // What Edit → Share Session… runs. From here on the dialog is modal: real input only.
  if (PROBE) {
    await runPy(p, 'import FreeCADGui as Gui' + NL + 'Gui.runCommand("Fcweb_ShareSession")');
  } else {
    await click(p, 'edit');
    await sl(1200);
    await click(p, 'item');
  }
  await sl(3000);
  await probe(p, 'general');
  if (!PROBE) {
    await click(p, 'start');
    const st = await until(async () => { const s = await sess(p); return s.id ? s : null; }, 90000);
    console.log('owner: session ' + (st ? st.id.slice(0, 8) : 'NONE'));
    await sl(2500);
    await click(p, 'copy');
    await sl(2000);
    // The visitor joins now, in a second context, so the Session page has someone on it.
    const pub = st && await until(async () => { const x = await sess(p); return x.v >= 1 ? x : null; }, 180000, 2000);
    let guest = null;
    if (pub) {
      const ctx = await b.createBrowserContext();
      guest = await ctx.newPage();
      await guest.setViewport({ width: W, height: H, deviceScaleFactor: 1 });
      await guest.evaluateOnNewDocument(`(() => { const f = () => { const j = document.getElementById('ld-join'); if (!j || j.hidden) return;
        const n = document.getElementById('ld-name'); if (n && !n.value) n.value = 'Sam'; const g = document.getElementById('ld-go'); if (g) g.click(); }; setInterval(f, 250); })();`);
      await guest.goto(URL + '?s=' + st.id, { waitUntil: 'domcontentloaded', timeout: 300000 });
      await ready(guest, 600000);
      await until(() => loaderGone(guest), 600000, 1500);
      const ap = await until(async () => { const s = await sess(guest); return s.applied ? s : null; }, 60000);
      console.log('guest: applied v' + (ap ? ap.applied : '?') + ' role=' + (ap ? ap.role : '?'));
    } else {
      console.log('owner: nothing published; is /share/health ok?');
    }
    await sl(1500);
    await click(p, 'session');
    await sl(1500);
    await click(p, 'refresh');
    await sl(5000);
    await r.stop();

    // ---- mcp ----------------------------------------------------------------------------
    r = await rec('mcp');
    await sl(1200);
    await click(p, 'mcp');
    await sl(2500);
    await click(p, 'enable');
    await sl(4000);
    await click(p, 'claude');
    await sl(3500);
    await r.stop();
    await p.keyboard.press('Escape');
    await sl(1500);
    if (guest) await guest.browserContext().close().catch(() => {});
    await runPy(p, [
      'import FreeCAD as App',
      'g = App.ParamGet("User parameter:BaseApp/Preferences/FCWeb/Sharing")',
      'g.SetBool("AllowAgent", False); g.SetBool("Enabled", False); App.saveParameter()',
    ].join(NL));
    await sl(3000);
    for (const n of ['share-owner', 'mcp']) {
      const f = path.join(OUT, n + '.webm');
      console.log(n + ' -> ' + f + ' (' + Math.round(fs.statSync(f).size / 1024) + ' KB)');
    }
  } else {
    // Probe mode: walk the pages by keyboard so their layout can be photographed without
    // knowing a single coordinate yet. Escape closes the dialog.
    await p.keyboard.press('Escape');
    await sl(1000);
    await runPy(p, 'import FreeCADGui as Gui' + NL + 'Gui.showPreferences("Sharing", 1)');
    await sl(2500);
    await probe(p, 'session');
    await p.keyboard.press('Escape');
    await sl(1000);
    await runPy(p, 'import FreeCADGui as Gui' + NL + 'Gui.showPreferences("Sharing", 2)');
    await sl(2500);
    await probe(p, 'mcp');
    await p.keyboard.press('Escape');
  }
  console.log('page errors: ' + (errs.length ? errs.slice(0, 5).join(' | ') : 'none'));
  await b.close().catch(() => {});
})().catch((e) => { console.log('DRIVER ' + e); process.exit(1); });
