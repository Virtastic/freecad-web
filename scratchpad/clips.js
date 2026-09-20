// SPDX-License-Identifier: LGPL-2.1-or-later
// Copyright (c) Virtastic
//
// Launch clips: short screen recordings of the shipped build doing real things under real
// mouse input, for the release posts. Records WebM through puppeteer's screencast (needs
// ffmpeg on PATH); scratchpad/clips-encode.sh turns each one into an mp4 and a gif.
//
//   CHROME_PATH=... node scratchpad/clips.js <base-url> <out-dir> [only]
//
// One browser, one profile, in this order:
//   boot          a first visit: the download, the boot, the Start page (fresh profile)
//   workbenches   every workbench activated in turn
//   engineblock   EngineBlock.FCStd opened, orbited and zoomed by mouse
//   bim           BIMExample.FCStd, the same
//   project-42mb  the 42 MB real project loaded from disk into the tab, then orbited
//   helm-stl      the 18 MB STL mesh
//   share-join    a SECOND browser context opening a share link and getting the model
//
// Documents are opened through the Python bridge (that is how the README shots do it too);
// everything the viewer then sees -- the orbit, the zoom, the join form -- is real input.
const fs = require('fs');
const path = require('path');
const puppeteer = require('puppeteer-core');

const URL = process.argv[2] || 'https://freecad.virtastic.app/freecad-gui.html';
const OUT = process.argv[3] || 'launch/assets/clips';
const ONLY = (process.argv[4] || '').split(',').filter(Boolean);
const CHROME = process.env.CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const SAMPLES = process.env.FCWEB_SAMPLES || 'local-serve-final';
const W = 1600, H = 900;
const sl = (ms) => new Promise((r) => setTimeout(r, ms));
const NL = String.fromCharCode(10);
const want = (n) => !ONLY.length || ONLY.includes(n);

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
  const el = document.getElementById('load');
  return !!el && el.classList.contains('hide');
});

async function until(fn, ms, every) {
  const t = Date.now();
  while (Date.now() - t < ms) {
    try { const v = await fn(); if (v) return v; } catch (e) { /* page busy */ }
    await sl(every || 1000);
  }
  return null;
}
const ready = (p, ms) => until(() => p.evaluate(
  () => !!(window.__fcWorkReady && window.fcInstance && window.fcInstance._malloc)), ms);

const CLEAN = [
  'from PySide6 import QtWidgets',
  'import FreeCAD as App, FreeCADGui as Gui',
  '# the cursor sits on the model for the whole orbit; preselection would paint it cyan',
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
  '# the first-run welcome panel (a fresh profile every run): press its Done button',
  'for bt in mw.findChildren(QtWidgets.QPushButton):',
  '    if bt.text().strip("&") == "Done" and bt.isVisible():',
  '        bt.click()',
].join(NL);

// Where the 3D view is. Qt draws into one canvas inside the shadow container.
const canvasCentre = (p) => p.evaluate(() => {
  const h = document.getElementById('qt-shadow-container');
  const cv = h && h.shadowRoot && h.shadowRoot.querySelector('canvas');
  const r = (cv || document.body).getBoundingClientRect();
  return { x: r.x + r.width * 0.58, y: r.y + r.height * 0.55 };
});

// A slow, human-looking orbit: left-drag under the Gesture style rotates.
async function orbit(p, dx, dy, steps, pause) {
  const c = await canvasCentre(p);
  await p.mouse.move(c.x, c.y);
  await p.mouse.down({ button: 'left' });
  for (let i = 1; i <= steps; i++) {
    const t = i / steps, e = t * t * (3 - 2 * t);            // ease in-out
    await p.mouse.move(c.x + dx * e, c.y + dy * e);
    await sl(pause || 30);
  }
  await p.mouse.up({ button: 'left' });
}
async function zoom(p, ticks, dir) {
  const c = await canvasCentre(p);
  await p.mouse.move(c.x, c.y);
  for (let i = 0; i < ticks; i++) { await p.mouse.wheel({ deltaY: dir * 120 }); await sl(120); }
}
async function tour(p) {
  await sl(1500);
  await orbit(p, 260, -90, 70);
  await sl(600);
  await zoom(p, 3, -1);
  await sl(800);
  await orbit(p, -180, 120, 60);
  await sl(600);
  await zoom(p, 3, 1);
  await sl(1200);
}

// The example files ship inside the payload; anything else is pushed in from disk in
// base64 chunks (the page's own fetch cannot reach a file: URL, and a second origin would
// need CORP headers under COEP).
async function pushFile(p, local, dest) {
  const buf = fs.readFileSync(local);
  const CH = 3 * 1024 * 1024;
  await p.evaluate(() => { window.__chunks = []; });
  for (let o = 0; o < buf.length; o += CH) {
    const b64 = buf.subarray(o, Math.min(o + CH, buf.length)).toString('base64');
    await p.evaluate((s) => {
      const bin = atob(s), a = new Uint8Array(bin.length);
      for (let i = 0; i < bin.length; i++) a[i] = bin.charCodeAt(i);
      window.__chunks.push(a);
    }, b64);
  }
  return p.evaluate((d) => {
    const n = window.__chunks.reduce((s, a) => s + a.length, 0);
    const all = new Uint8Array(n); let o = 0;
    for (const a of window.__chunks) { all.set(a, o); o += a.length; }
    window.fcInstance.FS.writeFile(d, all);
    delete window.__chunks;
    return n;
  }, dest);
}

async function openDoc(p, src, mark, isMesh) {
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
    isMesh ? '    import Mesh; _doc = App.newDocument("Model"); Mesh.insert(src, _doc.Name)'
           : '    App.openDocument(src)',
    '    Gui.activateWorkbench("PartDesignWorkbench")',
    '    App.ActiveDocument.recompute()',
    '    _v = Gui.activeDocument().activeView()',
    '    _v.viewAxonometric()',
    '    Gui.SendMsgToActiveView("ViewFit")',
    '    _v.setNavigationType("Gui::GestureNavigationStyle")',
    '    _n, _c = App.ActiveDocument.Name, len(App.ActiveDocument.Objects)',
    'except Exception as e:',
    '    _n, _c = "FAILED:%r" % (e,), -1',
    'sys.__stderr__.write("' + mark + ' doc=%s objects=%d' + '\\n' + '" % (_n, _c)); sys.__stderr__.flush()',
  ].join(NL));
  const line = await until(async () => {
    const m = (await logOf(p)).match(new RegExp(mark + '[^' + NL + ']*'));
    return m ? m[0] : null;
  }, 600000, 1500);
  await p.keyboard.press('Escape');
  await runPy(p, CLEAN);
  await sl(1500);
  await runPy(p, 'import FreeCADGui as Gui' + NL + 'Gui.SendMsgToActiveView("ViewFit")');
  await sl(2500);
  return line || 'TIMED OUT';
}

async function record(p, name, body) {
  const file = path.join(OUT, name + '.webm');
  const rec = await p.screencast({ path: file, fps: 25 });
  const t = Date.now();
  let note = '';
  try { note = (await body()) || ''; } catch (e) { note = 'FAILED ' + String(e).slice(0, 160); }
  await rec.stop();
  console.log(name + ': ' + Math.round((Date.now() - t) / 1000) + ' s ' + note + ' -> ' + file +
              ' (' + Math.round(fs.statSync(file).size / 1024) + ' KB)');
}

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const b = await puppeteer.launch({
    executablePath: CHROME, headless: false, defaultViewport: null,
    args: ['--no-sandbox', '--use-gl=angle', '--enable-features=SharedArrayBuffer',
           '--window-size=' + (W + 16) + ',' + (H + 120), '--hide-scrollbars'],
    protocolTimeout: 2400000, userDataDir: path.join(process.env.TEMP || '/tmp', 'fc-clips-' + Date.now()),
  });
  const errs = [];
  const p = (await b.pages())[0];
  p.on('pageerror', (e) => errs.push(String(e).slice(0, 120)));
  await p.setViewport({ width: W, height: H, deviceScaleFactor: 1 });

  // 1. A first visit. Fresh profile, so this is the real download and the real boot.
  if (want('boot')) {
    await record(p, 'boot', async () => {
      await p.goto(URL, { waitUntil: 'domcontentloaded', timeout: 300000 });
      const t = Date.now();
      if (!await ready(p, 600000)) return 'never Ready';
      const gone = await until(() => loaderGone(p), 120000);
      await sl(4000);
      return 'ready in ' + Math.round((Date.now() - t) / 1000) + ' s, loader hidden=' + !!gone;
    });
  } else {
    await p.goto(URL, { waitUntil: 'domcontentloaded', timeout: 300000 });
    if (!await ready(p, 600000)) { console.log('never Ready'); await b.close(); return; }
    await until(() => loaderGone(p), 120000);
    await sl(4000);
  }

  // 2. Every workbench, in turn.
  await runPy(p, CLEAN);
  await sl(1500);
  if (want('workbenches')) {
    await record(p, 'workbenches', async () => {
      await runPy(p, 'import FreeCADGui as Gui, sys' + NL + 'sys.__stderr__.write("WBLIST " + ",".join(sorted(Gui.listWorkbenches().keys())) + "\\n")');
      const wl = await until(async () => { const m = (await logOf(p)).match(/WBLIST (\S+)/); return m ? m[1] : null; }, 60000, 300);
      const wbs = wl ? wl.split(',') : ['PartDesignWorkbench', 'SketcherWorkbench', 'PartWorkbench', 'AssemblyWorkbench',
                   'DraftWorkbench', 'BIMWorkbench', 'FemWorkbench', 'CAMWorkbench', 'TechDrawWorkbench',
                   'MeshWorkbench', 'SpreadsheetWorkbench', 'OpenSCADWorkbench', 'SurfaceWorkbench',
                   'InspectionWorkbench', 'MaterialWorkbench', 'PointsWorkbench', 'ReverseEngineeringWorkbench',
                   'RobotWorkbench', 'TestWorkbench', 'StartWorkbench'];
      const out = [];
      for (const w of wbs) {
        await runPy(p, 'import FreeCADGui as Gui, sys' + NL +
          'sys.__stderr__.write("WB ' + w + ' %s\\n" % Gui.activateWorkbench("' + w + '"))');
        const l = await until(async () => { const m = (await logOf(p)).match(new RegExp('WB ' + w + ' \\w+')); return m ? m[0] : null; }, 60000, 300);
        out.push(l ? l.split(' ').pop() : '?');
        await sl(1100);
      }
      await sl(800);
      return 'activated ' + out.filter((x) => x === 'True').length + '/' + wbs.length + ' [' + wbs.map((w, i) => w.replace('Workbench', '') + (out[i] === 'True' ? '' : '!')).join(' ') + ']';
    });
  }

  // 3-6. Models under a real orbit.
  const models = [
    { n: 'engineblock', src: 'EngineBlock.FCStd' },
    { n: 'bim', src: 'BIMExample.FCStd' },
    { n: 'project-42mb', src: '/home/web_user/900a_GA3DtechProject_v1.0.FCStd', local: path.join(SAMPLES, '900a_GA3DtechProject_v1.0.FCStd') },
    { n: 'helm-stl', src: '/home/web_user/dovahkiin_helm_reforged.stl', local: path.join(SAMPLES, 'dovahkiin_helm_reforged.stl'), mesh: true },
  ];
  for (const m of models) {
    if (!want(m.n)) continue;
    if (m.local) {
      const n = await pushFile(p, m.local, m.src);
      console.log(m.n + ': pushed ' + Math.round(n / 1048576) + ' MB into the tab');
    }
    // A big file: record the load too, the progress is the point.
    const t = Date.now();
    const line = await openDoc(p, m.src, 'CLIP_' + m.n.replace(/-/g, '_'), m.mesh);
    const loaded = Math.round((Date.now() - t) / 1000);
    await runPy(p, CLEAN);
    await sl(1500);
    await record(p, m.n, async () => { await tour(p); return line.trim() + ' (opened in ' + loaded + ' s)'; });
  }

  // 7. The share link, from the visitor's side.
  if (want('share-join')) {
    const line = await openDoc(p, 'PartDesignExample.FCStd', 'CLIP_share');
    await runPy(p, [
      'import FreeCAD as App',
      'p = App.ParamGet("User parameter:BaseApp/Preferences/FCWeb/Sharing")',
      'p.SetString("DisplayName", "Michael")',
      'p.SetBool("Enabled", True)',
      'App.saveParameter()',
    ].join(NL));
    const st = await until(async () => { const s = await sess(p); return s.id ? s : null; }, 90000);
    const pub = st && await until(async () => { const x = await sess(p); return x.v >= 1 ? x : null; }, 180000, 2000);
    if (!pub) {
      console.log('share-join: no published session (' + JSON.stringify(st) + '); is /share/health ok on ' + URL + '?');
    } else {
      const ctx = await b.createBrowserContext();
      const g = await ctx.newPage();
      g.on('pageerror', (e) => errs.push('guest: ' + String(e).slice(0, 120)));
      await g.setViewport({ width: W, height: H, deviceScaleFactor: 1 });
      // The visitor types a name into the join form on the loading screen. The form exists
      // before the app does, so the typing is real keyboard input into a real input.
      const gurl = URL + (URL.indexOf('?') >= 0 ? '&' : '?') + 's=' + st.id;
      await record(g, 'share-join', async () => {
        await g.goto(gurl, { waitUntil: 'domcontentloaded', timeout: 300000 });
        const form = await until(() => g.evaluate(() => {
          const f = document.getElementById('ld-join'); return !!f && !f.hidden; }), 120000, 300);
        if (!form) return 'join form never appeared';
        await sl(800);
        await g.click('#ld-name');
        await g.keyboard.type('Sam', { delay: 90 });
        await sl(500);
        await g.click('#ld-go');
        if (!await ready(g, 600000)) return 'guest never Ready';
        const gone = await until(() => loaderGone(g), 600000, 1500);
        const ap = await until(async () => { const s = await sess(g); return s.applied ? s : null; }, 60000);
        await sl(2500);
        await runPy(g, CLEAN + NL + 'Gui.activeDocument().activeView().setNavigationType("Gui::GestureNavigationStyle")');
        await sl(1000);
        await orbit(g, 220, -80, 60);
        await sl(1500);
        return 'loader hidden=' + !!gone + ' applied v' + (ap ? ap.applied : '?') + ' role=' + (ap ? ap.role : '?') + ' owner ' + line.trim();
      });
      await ctx.close().catch(() => {});
    }
    await runPy(p, [
      'import FreeCAD as App',
      'p = App.ParamGet("User parameter:BaseApp/Preferences/FCWeb/Sharing")',
      'p.SetBool("Enabled", False)',
      'App.saveParameter()',
    ].join(NL));
    await sl(3000);
  }

  console.log('page errors: ' + (errs.length ? errs.slice(0, 5).join(' | ') : 'none'));
  await b.close().catch(() => {});
})().catch((e) => { console.log('DRIVER ' + e); process.exit(1); });
