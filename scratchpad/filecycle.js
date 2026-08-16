// Save to a real file and open it back, the way a user does: Cmd/Ctrl+S produces a
// browser DOWNLOAD, Cmd/Ctrl+O opens the browser's FILE PICKER.
//
// The most fundamental workflow there is, and it had only ever been exercised through
// Python (doc.saveAs / openDocument), which skips both bridges entirely.
//
// Usage: node scratchpad/filecycle.js [url]
const puppeteer = require('puppeteer-core');
const fs = require('fs');
const path = require('path');
const CHROME = process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';  // set CHROME_PATH to run off macOS
const sl = (ms) => new Promise((r) => setTimeout(r, ms));
const URL = process.argv[2] || 'http://localhost:8792/index.html';
const DL = '/tmp/fc-downloads';

const run = (p, code) => p.evaluate((c) => {
  const m = window.fcInstance;
  const n = new TextEncoder().encode(c).length + 1; const q = m._malloc(n); m.stringToUTF8(c, q, n);
  (window.fcRunPy || ((mm, pp) => { mm._fcweb_run_python(pp); mm._free(pp); }))(m, q);
}, code);
const readLog = (p) => p.evaluate(() => document.getElementById('log').textContent);
const last = async (p, re) => { const m = (await readLog(p)).match(re) || []; return m.length ? m[m.length - 1] : ''; };

(async () => {
  fs.rmSync(DL, { recursive: true, force: true });
  fs.mkdirSync(DL, { recursive: true });
  const b = await puppeteer.launch({ executablePath: CHROME, headless: false, defaultViewport: null,
    args: ['--no-sandbox', '--use-gl=angle', '--use-angle=metal', '--window-size=1400,900'],
    protocolTimeout: 1200000, userDataDir: '/tmp/fc-filecycle' });
  const p = (await b.pages())[0];
  const errs = [];
  p.on('pageerror', (e) => errs.push(String(e).slice(0, 140)));
  const cdp = await p.createCDPSession();
  await cdp.send('Browser.setDownloadBehavior', { behavior: 'allow', downloadPath: DL });

  await p.goto(URL, { waitUntil: 'domcontentloaded', timeout: 300000 });
  const t0 = Date.now();
  while (Date.now() - t0 < 300000) {
    if (await p.evaluate(() => !!(window.fcInstance && window.fcInstance._malloc))) break;
    await sl(1000);
  }
  for (let i = 0; i < 40; i++) {
    await sl(3000);
    await run(p, 'import sys, FreeCAD\nsys.__stderr__.write("RDY %d\\n" % len(FreeCAD.__unit_test__))\nsys.__stderr__.flush()\n');
    await sl(1200);
    const m = [...(await readLog(p)).matchAll(/RDY (\d+)/g)].pop();
    if (m && +m[1] > 0) break;
  }

  // a document worth saving: a box with a distinctive size
  await run(p, `
import sys
import FreeCAD as App, FreeCADGui as Gui
d = App.newDocument("RoundTrip")
box = d.addObject("Part::Box", "Box")
box.Length = 13; box.Width = 17; box.Height = 19      # 4199, hard to produce by accident
d.recompute()
Gui.SendMsgToActiveView("ViewFit")
sys.__stderr__.write("MADE volume=%.1f\\n" % box.Shape.Volume); sys.__stderr__.flush()
`);
  await sl(4000);
  console.log((await last(p, /MADE [^\n]*/g)) || 'no document');

  // SAVE: the shell's Cmd/Ctrl+S handler produces a real browser download
  const MOD = process.platform === 'darwin' ? 'Meta' : 'Control';
  await p.keyboard.down(MOD); await p.keyboard.press('KeyS'); await p.keyboard.up(MOD);

  let saved = null;
  for (let i = 0; i < 60 && !saved; i++) {
    await sl(2000);
    const files = fs.readdirSync(DL).filter((f) => f.endsWith('.FCStd'));
    if (files.length) saved = path.join(DL, files[0]);
  }
  if (!saved) {
    console.log('SAVE FAILED: no .FCStd landed in the download dir');
    console.log('page errors: ' + (errs.length ? errs.join(' | ') : 'none'));
    await b.close().catch(() => {}); process.exit(0);
  }
  console.log(`saved: ${path.basename(saved)} (${fs.statSync(saved).size} bytes)`);

  // close it so the reopen cannot be reading the in-memory document
  await run(p, `
import sys
import FreeCAD as App
for n in list(App.listDocuments()):
    App.closeDocument(n)
sys.__stderr__.write("CLOSED docs=%d\\n" % len(App.listDocuments())); sys.__stderr__.flush()
`);
  await sl(3000);
  console.log((await last(p, /CLOSED [^\n]*/g)));

  // OPEN: Cmd/Ctrl+O opens the browser file picker; hand it the file we just saved
  const chooserP = p.waitForFileChooser({ timeout: 60000 });
  await p.keyboard.down(MOD); await p.keyboard.press('KeyO'); await p.keyboard.up(MOD);
  let chooser;
  try { chooser = await chooserP; } catch (e) {
    console.log('OPEN FAILED: no file picker appeared');
    await b.close().catch(() => {}); process.exit(0);
  }
  await chooser.accept([saved]);
  await sl(12000);

  await run(p, `
import sys
import FreeCAD as App
docs = App.listDocuments()
out = "docs=%s" % list(docs)
for n in docs:
    for o in App.getDocument(n).Objects:
        sh = getattr(o, "Shape", None)
        if sh is not None and not sh.isNull():
            out += " | %s volume=%.1f" % (o.Name, sh.Volume)
sys.__stderr__.write("REOPEN %s\\n" % out); sys.__stderr__.flush()
`);
  await sl(3000);
  console.log((await last(p, /REOPEN [^\n]*/g)) || 'no reopen line');
  console.log('  (13 x 17 x 19 = 4199 -- the same solid must come back)');
  console.log('page errors: ' + (errs.length ? errs.slice(0, 3).join(' | ') : 'none'));
  await p.screenshot({ path: '/tmp/filecycle.png' }).catch(() => {});
  await b.close().catch(() => {}); process.exit(0);
})().catch((e) => { console.log('DRIVER ' + String(e).slice(0, 200)); process.exit(0); });
