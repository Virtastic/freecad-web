// Is FreeCAD's Start page a Document? fcweb_share._mine() and the pin logic both exclude
// documents whose FileName is under /freecad/ and both call that "FreeCAD's own start
// page". If Start is a VIEW rather than a document, neither check does what it says, and
// the only thing either excludes is a bundled example the user chose to open.
//
//   node scratchpad/_docprobe.js http://localhost:8081/freecad-gui.html
const puppeteer = require('puppeteer-core');
const sl = (ms) => new Promise((r) => setTimeout(r, ms));
const NL = String.fromCharCode(10);
const BS = String.fromCharCode(92);
const URL = process.argv[2];
const CHROME = process.env.CHROME_PATH;

const runPy = (p, c) => p.evaluate((c) => {
  const m = window.fcInstance;
  const n = new TextEncoder().encode(c).length + 1;
  const q = m._malloc(n);
  m.stringToUTF8(c, q, n);
  (window.fcRunPy || ((mm, pp) => { mm._fcweb_run_python(pp); mm._free(pp); }))(m, q);
}, c);

(async () => {
  const b = await puppeteer.launch({
    executablePath: CHROME, headless: false, defaultViewport: null,
    args: ['--no-sandbox', '--use-gl=angle', '--window-size=1400,900'],
    protocolTimeout: 1200000, userDataDir: '/tmp/fc-docprobe-' + Date.now(),
  });
  const p = (await b.pages())[0];
  await p.goto(URL, { waitUntil: 'domcontentloaded', timeout: 300000 });
  const t = Date.now();
  while (Date.now() - t < 420000) {
    if (await p.evaluate(() => !!window.__fcWorkReady)) break;
    await sl(1000);
  }
  await sl(15000);

  // One statement, everything guarded, one marker: a throw before the flush is why the
  // first two attempts printed nothing at all.
  await runPy(p, [
    'import sys',
    'import FreeCAD as App',
    'try:',
    '    _docs = App.listDocuments()',
    '    _rows = [(n, getattr(d, "FileName", ""), getattr(d, "Label", "")) for n, d in _docs.items()]',
    '    _act = App.ActiveDocument.Name if App.ActiveDocument else None',
    '    _out = "docs=%d rows=%r active=%r" % (len(_docs), _rows, _act)',
    'except Exception as e:',
    '    _out = "FAILED %r" % (e,)',
    'sys.__stderr__.write("PROBEOUT " + _out + "' + BS + 'n")',
    'sys.__stderr__.flush()',
  ].join(NL));

  let done = false;
  for (let i = 0; i < 90 && !done; i += 1) {
    const log = await p.evaluate(() => (document.getElementById('log') || {}).textContent || '');
    const hits = log.match(/PROBEOUT [^\n]*/g);
    if (hits) { console.log(hits.join(NL)); done = true; break; }
    await sl(2000);
  }
  if (!done) {
    const log = await p.evaluate(() => (document.getElementById('log') || {}).textContent || '');
    console.log('no PROBEOUT line. tail of log: ' + log.slice(-500));
  }
  await b.close().catch(() => {});
})();
