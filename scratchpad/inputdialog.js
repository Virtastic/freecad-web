// Does a Python-triggered QInputDialog actually return what the user TYPED?
//
// This is the check that closes the "every macro prompt silently cancels" defect. The
// stubs that caused it are gone (CI enforces that), and the following were verified live
// on production without a harness:
//
//   - all four statics report NATIVE, not a lambda
//   - a native QInputDialog composites: visible=True size=208x109 children=4
//   - calling getText SUSPENDS the interpreter under JSPI (__fcPyBusy stays true) instead
//     of returning a stub value immediately
//   - the modal is real, and Qt reports its widgets:
//       modal=QInputDialog title='Probe'  BTN OK @ 581,349  BTN Cancel @ 677,349
//       EDIT @ 629,315
//
// What none of that proves is the last step: type into it, press OK, and get the string
// back. That needs TRUSTED input. Events made with dispatchEvent() are untrusted and Qt
// ignores them here, which is why this has to be a Puppeteer harness -- CDP input is
// trusted, the same reason every other real-input harness in this directory exists.
//
//   node scratchpad/inputdialog.js [url]
//
// Exits non-zero on failure so it can gate a release.
const puppeteer = require('puppeteer-core');

const URL = process.argv[2] || 'https://freecad.virtastic.app/';
const CHROME = process.env.CHROME_PATH
  || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

(async () => {
  const browser = await puppeteer.launch({
    executablePath: CHROME,
    headless: false,               // Qt-wasm needs a real compositor
    args: ['--enable-features=SharedArrayBuffer', '--window-size=1400,900'],
    defaultViewport: { width: 1280, height: 720 },
  });
  const page = (await browser.pages())[0];
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e)));

  console.log('booting', URL);
  await page.goto(URL, { waitUntil: 'domcontentloaded', timeout: 0 });

  // Wait for Ready, then for the dialog shim install (fires ~8 s after Qt onLoaded).
  await page.waitForFunction(
    () => /Ready/i.test((document.getElementById('bootstatus') || {}).textContent || ''),
    { timeout: 600000 });
  await sleep(12000);

  const py = async (code) => page.evaluate((src) => {
    const m = window.fcInstance;
    const n = new TextEncoder().encode(src).length + 1;
    const p = m._malloc(n); m.stringToUTF8(src, p, n);
    window.fcRunPy(m, p);
  }, code);
  const read = (p) => page.evaluate((f) => {
    try { return new TextDecoder().decode(window.fcInstance.FS.readFile(f)); }
    catch (e) { return null; }
  }, p);

  await py("import os\n" +
           "for f in ('/tmp/geo.txt','/tmp/typed.txt'):\n" +
           "    try: os.remove(f)\n" +
           "    except Exception: pass");
  await sleep(1500);

  // Qt's event loop keeps running while the interpreter is suspended in a modal, so a
  // timer scheduled BEFORE the blocking call fires while the dialog is up and publishes
  // where its widgets actually are. Hardcoding coordinates would be guessing.
  const WANT = 'Flange';
  await py([
    "from PySide6 import QtWidgets as W, QtCore as C",
    "def _pub():",
    "    d = W.QApplication.activeModalWidget()",
    "    if d is None:",
    "        open('/tmp/geo.txt','w').write('NO MODAL'); return",
    "    g = d.geometry(); out = []",
    "    for b in d.findChildren(W.QPushButton):",
    "        c = b.mapTo(d, b.rect().center())",
    "        out.append('BTN|%s|%d|%d' % (b.text().replace('&',''), g.x()+c.x(), g.y()+c.y()))",
    "    for e in d.findChildren(W.QLineEdit):",
    "        c = e.mapTo(d, e.rect().center())",
    "        out.append('EDIT|%d|%d' % (g.x()+c.x(), g.y()+c.y()))",
    "    open('/tmp/geo.txt','w').write('\\n'.join(out))",
    "C.QTimer.singleShot(2000, _pub)",
    "try:",
    "    v, ok = W.QInputDialog.getText(None, 'Probe', 'Type a name:')",
    "    open('/tmp/typed.txt','w').write('%r|%r' % (v, ok))",
    "except Exception as e:",
    "    open('/tmp/typed.txt','w').write('THREW %s' % e)",
  ].join('\n'));

  let geo = null;
  for (let i = 0; i < 15 && !geo; i++) { await sleep(1000); geo = await read('/tmp/geo.txt'); }
  if (!geo || geo === 'NO MODAL') {
    console.error('FAIL: no modal appeared — getText did not open a dialog');
    await browser.close(); process.exit(1);
  }
  console.log('dialog widgets:\n  ' + geo.split('\n').join('\n  '));

  const edit = geo.split('\n').find((l) => l.startsWith('EDIT|'));
  const ok = geo.split('\n').find((l) => l.startsWith('BTN|OK|'));
  if (!edit || !ok) {
    console.error('FAIL: dialog is missing a text field or an OK button');
    await browser.close(); process.exit(1);
  }
  const [, ex, ey] = edit.split('|');
  const [, , ox, oy] = ok.split('|');

  // Trusted input from here on.
  await page.mouse.click(+ex, +ey);
  await sleep(400);
  await page.keyboard.type(WANT, { delay: 60 });
  await sleep(400);
  await page.mouse.click(+ox, +oy);

  let out = null;
  for (let i = 0; i < 20 && !out; i++) { await sleep(1000); out = await read('/tmp/typed.txt'); }

  console.log('getText returned:', out);
  console.log('page errors:', errors.length);

  const pass = !!out && out.includes(WANT) && /True/.test(out) && errors.length === 0;
  console.log(pass
    ? `PASS — typed ${WANT}, macro received it`
    : `FAIL — expected value=${WANT} ok=True, got ${out}`);
  await browser.close();
  process.exit(pass ? 0 : 1);
})();
