// SPDX-License-Identifier: LGPL-2.1-or-later
// Copyright (c) Virtastic
//
// The three pictures the README could not take from a document: the sharing UI itself.
// Starts a real session against a real backend, photographs the owner's Preferences pages,
// then joins the link from a SECOND browser context and photographs what a visitor sees.
//
//   node scratchpad/shareshots.js <base-url> <out-dir>
//
// Needs the session container: the page reports "sharing is not available on this site"
// without it, and every shot below is then a picture of a disabled button. Check first:
//   curl -fsS <base-url-origin>/share/health
//
// Headful, same as shots.js: headless GL breaks Coin's hooks and the viewport comes back
// empty. Two traps already paid for:
//   - a modal Preferences dialog PARKS the Python bridge, so nothing can be driven through
//     runPy until it closes. Close it with a real Escape key, never another runPy.
//   - the join form lives inside the loading screen, so the viewer context needs its filler
//     installed as an init script BEFORE navigation, not after Ready.
const fs = require('fs');
const path = require('path');
const puppeteer = require('puppeteer-core');

const URL = process.argv[2] || 'http://localhost:8080/freecad-gui.html';
const OUT = process.argv[3] || 'docs/images';
const CHROME = process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const sl = (ms) => new Promise((r) => setTimeout(r, ms));
const NL = String.fromCharCode(10);

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
  return { id: s.id || '', holder: !!s.holder, role: s.role || '', v: s.v, applied: s.applied, agentUrl: s.agentUrl || '' };
});

async function ready(p, ms) {
  const t = Date.now();
  while (Date.now() - t < ms) {
    if (await p.evaluate(() => !!(window.__fcWorkReady && window.fcInstance && window.fcInstance._malloc))) return true;
    await sl(1000);
  }
  return false;
}

async function until(fn, ms, every) {
  const t = Date.now();
  while (Date.now() - t < ms) {
    try { const v = await fn(); if (v) return v; } catch (e) { /* page busy */ }
    await sl(every || 1000);
  }
  return null;
}

// The visitor answers the name/password form the loading screen shows. Polled, not
// observed: an init script runs before documentElement exists and observe() would throw.
const joinScript = (name) => `(() => {
  const fill = () => {
    const f = document.getElementById('ld-join');
    if (!f || f.hidden) return;
    const n = document.getElementById('ld-name');
    if (n && !n.value) n.value = ${JSON.stringify(name)};
    const go = document.getElementById('ld-go');
    if (go) go.click();
  };
  setInterval(fill, 250);
})();`;

// Anything floating over the window: the Tasks panel, the notification list, a tooltip.
// Same list shots.js hides, for the same reason -- a README frame of a model with a task
// panel parked across it reads as a screenshot someone forgot to tidy.
const CLEAN = [
  'from PySide6 import QtWidgets',
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

const shot = async (p, name) => {
  const f = path.join(OUT, name + '.png');
  await p.screenshot({ path: f });
  console.log('  wrote ' + f + ' (' + Math.round(fs.statSync(f).size / 1024) + ' KB)');
};

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const b = await puppeteer.launch({
    executablePath: CHROME, headless: false, defaultViewport: null,
    args: ['--no-sandbox', '--use-gl=angle', '--enable-features=SharedArrayBuffer',
           '--window-size=1680,1050', '--hide-scrollbars'],
    protocolTimeout: 2400000, userDataDir: '/tmp/fc-shareshots-' + Date.now(),
  });
  const errs = [];
  const owner = (await b.pages())[0];
  owner.on('pageerror', (e) => errs.push('owner: ' + String(e).slice(0, 120)));

  console.log('owner: booting ' + URL);
  await owner.goto(URL, { waitUntil: 'domcontentloaded', timeout: 300000 });
  if (!await ready(owner, 420000)) { console.log('FAILED: owner never reached Ready'); await b.close(); return; }
  await sl(12000);
  await owner.setViewport({ width: 1460, height: 900, deviceScaleFactor: 2 });
  await sl(5000);

  // A document worth looking at. The example files ship inside the payload.
  await runPy(owner, [
    'import sys, glob, os',
    'import FreeCAD as App, FreeCADGui as Gui',
    'import shutil',
    'hits = glob.glob("/freecad/**/PartDesignExample.FCStd", recursive=True)',
    // Copy it out of /freecad/ first. fcweb_share._mine() excludes every document whose
    // FileName starts with /freecad/ -- that is where FreeCAD's own bundled files and the
    // start page live, and publishing those would be wrong. Opening the example IN PLACE
    // therefore shares a session with nothing in it ("sharing with no document open:
    // nothing to publish"), which is what three attempts at the visitor shot photographed.
    'mine = "/home/web_user/PartDesignExample.FCStd"',
    'shutil.copyfile(hits[0], mine) if hits else None',
    'App.openDocument(mine) if hits else App.newDocument("Model")',
    'App.ActiveDocument.recompute()',
    '_v = Gui.activeDocument().activeView() if Gui.activeDocument() else None',
    'hasattr(_v, "viewAxonometric") and _v.viewAxonometric()',
    'Gui.SendMsgToActiveView("ViewFit")',
    'sys.__stderr__.write("SHARESHOT doc=%s objects=%d' + '\\n' + '" % (App.ActiveDocument.Name, len(App.ActiveDocument.Objects))); sys.__stderr__.flush()',
  ].join(NL));
  const docLine = await until(async () => {
    const m = (await logOf(owner)).match(/SHARESHOT [^\n]*/);
    return m ? m[0] : null;
  }, 300000);
  console.log('owner: ' + (docLine || 'document never opened'));

  // Start sharing exactly the way the General page does: set the parameters, save.
  await runPy(owner, [
    'import FreeCAD as App',
    'p = App.ParamGet("User parameter:BaseApp/Preferences/FCWeb/Sharing")',
    'p.SetString("DisplayName", "Michael")',
    'p.SetBool("Enabled", True)',
    'App.saveParameter()',
  ].join(NL));
  const st = await until(async () => { const s = await sess(owner); return s.id ? s : null; }, 90000);
  if (!st) { console.log('FAILED: no session id -- is the session container running?'); await b.close(); return; }
  console.log('owner: session ' + st.id.slice(0, 8) + ' holder=' + st.holder + ' role=' + st.role);
  // The unchecked link in the chain the first three attempts all fell through: waiting for
  // this and then ignoring the answer. Without a published version there is nothing for a
  // visitor to open, and the visitor shot is a picture of a first-run FreeCAD.
  // Ask the SESSION STATE, not the log element: the on-screen log renders its channel
  // differently from the console ("publish  pushed v1 (...)"), so matching the console's
  // wording against the DOM reported a failure over a perfectly good publish.
  const pub = await until(async () => { const x = await sess(owner); return x.v >= 1 ? x : null; }, 180000, 2000);
  console.log('owner: published v1 = ' + !!pub + ', state ' + JSON.stringify(await sess(owner)));
  if (!pub) {
    const ring = await owner.evaluate(() => (window.__fcSessionRing || []).slice(-12)).catch(() => []);
    console.log('owner ring: ' + JSON.stringify(ring));
    console.log('FAILED: nothing was published, so there is nothing for a visitor to open.');
    await b.close();
    return;
  }

  // The visitor joins FIRST. The Session page exists to show who else is here, and with
  // nobody there it photographs an empty list and four greyed buttons -- which is exactly
  // the picture the first run produced. A separate browser CONTEXT, so separate storage:
  // a second tab of the same profile rejoins as the owner, not as a guest.
  console.log('guest: joining the link');
  const ctx = await b.createBrowserContext();
  const guest = await ctx.newPage();
  guest.on('pageerror', (e) => errs.push('guest: ' + String(e).slice(0, 120)));
  await guest.evaluateOnNewDocument(joinScript('Sam'));
  await guest.setViewport({ width: 1460, height: 900, deviceScaleFactor: 2 });
  const gurl = URL + (URL.indexOf('?') >= 0 ? '&' : '?') + 's=' + st.id;
  console.log('  guest url ' + gurl);
  await guest.goto(gurl, { waitUntil: 'domcontentloaded', timeout: 300000 });
  // Did the page even take the link as a session link? SID_RE wants s=<32 hex>; anything
  // else boots a plain first-run FreeCAD, which is what the first attempt photographed.
  const mode = await until(async () => guest.evaluate(
    () => (window.__fcSession && window.__fcSession.mode) || (window.__fcSessionJoining ? 'joining' : null)), 60000);
  console.log('  guest boot mode: ' + (mode || 'NOT session mode -- the link was not recognised'));
  if (!await ready(guest, 420000)) { console.log('  guest never reached Ready'); }
  // __fcWorkReady is Qt's signal, NOT "the shared document is on screen": in session mode the
  // loader deliberately stays up past Ready until the document arrives (__fcSessionJoining).
  // Waiting on it photographed the loading screen mid-"OPENING THE SHARED DOCUMENT". The
  // real signal is the overlay going away -- __maybeReveal() puts .hide on #load.
  const shown = await until(async () => guest.evaluate(() => {
    const el = document.getElementById('load');
    return !!el && el.classList.contains('hide');
  }), 600000, 2000);
  console.log('  guest loader dismissed: ' + !!shown);
  const applied = await until(async () => { const s = await sess(guest); return s.applied ? s : null; }, 60000);
  console.log('  guest applied v' + (applied ? applied.applied : '?') + ' role=' + (applied ? applied.role : '?'));
  if (!applied) {
    console.log('  guest state: ' + JSON.stringify(await guest.evaluate(() => {
      const s = window.__fcSession || {};
      return { mode: s.mode, id: s.id, ended: s.ended, note: s.note, joining: !!window.__fcSessionJoining };
    }).catch((e) => String(e))));
    const ring = await guest.evaluate(() => (window.__fcSessionRing || []).slice(-10)).catch(() => []);
    console.log('  guest ring: ' + JSON.stringify(ring));
    console.log('  guest loader: ' + await guest.evaluate(
      () => ((document.getElementById('load') || {}).innerText || '').slice(0, 300)).catch(() => ''));
  }
  await sl(8000);
  await runPy(guest, CLEAN);
  await sl(3000);
  await runPy(guest, 'import FreeCADGui as Gui' + NL + 'Gui.SendMsgToActiveView("ViewFit")');
  await sl(7000);
  await shot(guest, 'share-viewer');
  await owner.bringToFront();
  await sl(4000);

  // 1a. Preferences > Sharing > General: start/stop, the link, the passwords. Index order
  // is the registration order in fcweb_share.py: General, Session, MCP.
  console.log('shot 1a: the general page');
  await runPy(owner, 'import FreeCADGui as Gui' + NL + 'Gui.showPreferences("Sharing", 0)');
  await sl(9000);
  await shot(owner, 'share-general');
  await owner.keyboard.press('Escape');
  await sl(5000);

  // 1b. Preferences > Sharing > Session: who is here and what you can do about it.
  console.log('shot 1b: the session page');
  await runPy(owner, 'import FreeCADGui as Gui' + NL + 'Gui.showPreferences("Sharing", 1)');
  await sl(9000);
  await shot(owner, 'share-session');
  await owner.keyboard.press('Escape');
  await sl(5000);

  // 2. The MCP page, with an endpoint actually minted so the URL and copy buttons are live.
  console.log('shot 2: the MCP page');
  await runPy(owner, [
    'import FreeCAD as App',
    'p = App.ParamGet("User parameter:BaseApp/Preferences/FCWeb/Sharing")',
    'p.SetBool("AllowAgent", True)',
    'p.SetBool("AgentArm", True)',
    'App.saveParameter()',
  ].join(NL));
  await until(async () => (await sess(owner)).agentUrl, 90000);
  // Enabling raises a page toast that then sits over the corner of the shot. It has its
  // own close button; the page keeps it up until something dismisses it.
  // Found by its TEXT, not by a class name: the notifier lives outside this file (it is
  // fcwebNotify, defined in the built shell) and guessing at its markup photographed the
  // toast anyway. Walk up to the positioned container and hide that.
  await owner.evaluate(() => {
    for (const el of document.querySelectorAll('div, section, aside')) {
      if (!/assistant enabled/i.test(el.textContent || '')) continue;
      let n = el;
      for (let i = 0; i < 6 && n && n.parentElement; i += 1) {
        const pos = getComputedStyle(n).position;
        if (pos === 'fixed' || pos === 'absolute') break;
        n = n.parentElement;
      }
      if (n) n.style.display = 'none';
    }
  }).catch(() => {});
  await sl(1500);
  await runPy(owner, 'import FreeCADGui as Gui' + NL + 'Gui.showPreferences("Sharing", 2)');
  await sl(9000);
  await shot(owner, 'share-mcp');
  await owner.keyboard.press('Escape');
  await sl(4000);

  // Kill the session, so the link and the MCP token legible in these shots are dead before
  // the images go anywhere. Localhost-only to begin with; this makes it moot either way.
  await runPy(owner, [
    'import FreeCAD as App',
    'p = App.ParamGet("User parameter:BaseApp/Preferences/FCWeb/Sharing")',
    'p.SetBool("AllowAgent", False)',
    'p.SetBool("Enabled", False)',
    'App.saveParameter()',
  ].join(NL));
  await sl(6000);
  console.log('session stopped: ' + JSON.stringify(await sess(owner)));

  console.log('page errors: ' + (errs.length ? errs.slice(0, 5).join(' | ') : 'none'));
  await b.close().catch(() => {});
})();
