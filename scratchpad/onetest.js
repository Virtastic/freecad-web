// Run the individual tests of ONE FreeCAD suite, one per _fcweb_run_python call.
//
// Exists because a suite that hangs takes the main thread with it: nothing can read the
// page log afterwards, so in-page progress logging cannot name the culprit. Driving one
// test per call from node means the test that never returns is the one we are still
// waiting on when the timeout fires.
//
// Usage: node scratchpad/onetest.js <SuiteName> [url] [per-test-timeout-ms]
const puppeteer = require('puppeteer-core');
const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const sl = (ms) => new Promise((r) => setTimeout(r, ms));
const SUITE = process.argv[2] || 'Document';
const URL = process.argv[3] || 'http://localhost:8792/index.html';
const PER = Number(process.argv[4] || 60000);

const run = (p, code) => p.evaluate((c) => {
  const m = window.fcInstance;
  const n = new TextEncoder().encode(c).length + 1; const q = m._malloc(n); m.stringToUTF8(c, q, n);
  (window.fcRunPy || ((mm, pp) => { mm._fcweb_run_python(pp); mm._free(pp); }))(m, q);
}, code);
const readLog = (p) => p.evaluate(() => document.getElementById('log').textContent);

async function runAwait(p, code, re, timeoutMs) {
  await run(p, code);
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    await sl(1500);
    let log;
    try { log = await readLog(p); } catch (e) { return { dead: String(e).slice(0, 120) }; }
    const m = log.match(re);
    if (m) return { log, m };
  }
  return { timeout: true };
}

(async () => {
  const b = await puppeteer.launch({ executablePath: CHROME, headless: false, defaultViewport: null,
    args: ['--no-sandbox', '--use-gl=angle', '--use-angle=metal', '--window-size=1300,850'],
    protocolTimeout: 3600000, userDataDir: '/tmp/fc-onetest' });
  const p = (await b.pages())[0];
  await p.goto(URL, { waitUntil: 'domcontentloaded', timeout: 300000 });
  const t0 = Date.now();
  while (Date.now() - t0 < 300000) {
    if (await p.evaluate(() => !!(window.fcInstance && window.fcInstance._malloc))) break;
    await sl(1000);
  }
  let ready = false;
  for (let i = 0; i < 60 && !ready; i++) {
    await sl(3000);
    try {
      const r = await runAwait(p, 'import sys, FreeCAD\n'
        + 'sys.__stderr__.write("OT READY %d\\n" % len(FreeCAD.__unit_test__)); sys.__stderr__.flush()\n',
        /OT READY (\d+)/, 8000);
      const mm = r.log ? [...r.log.matchAll(/OT READY (\d+)/g)].pop() : null;
      ready = !!mm && Number(mm[1]) > 0;
    } catch (e) { /* booting */ }
  }
  if (!ready) { console.log('DRIVER not ready'); await b.close().catch(() => {}); process.exit(0); }

  const list = await runAwait(p, `
import sys, unittest
ids = []
def walk(s):
    for t in s:
        if isinstance(t, unittest.TestSuite): walk(t)
        else: ids.append(t.id())
walk(unittest.defaultTestLoader.loadTestsFromName(${JSON.stringify(SUITE)}))
sys.__stderr__.write("OT IDS " + ",".join(ids) + "|END\\n"); sys.__stderr__.flush()
`, /OT IDS ([^\n|]*)\|END/, 30000);
  const ids = list.m ? list.m[1].split(',').filter(Boolean) : [];
  console.log(`PLAN ${ids.length} tests in ${SUITE}`);

  const printed = new Set(list.log.match(/OT [^\n]*/g) || []);
  for (const id of ids) {
    const short = id.split('.').slice(-2).join('.');
    const py = `
import sys, unittest
try:
    s = unittest.defaultTestLoader.loadTestsFromName(${JSON.stringify(id)})
    r = unittest.TextTestRunner(stream=open("/dev/null","w"), verbosity=0).run(s)
    tail = ""
    for who, tb in (list(r.failures) + list(r.errors))[:1]:
        tail = " | " + tb.strip().splitlines()[-1][:110]
    sys.__stderr__.write("OT %s ok=%s%s\\n" % (${JSON.stringify(short)},
        (r.wasSuccessful() and "yes" or "NO"), tail))
except Exception as e:
    sys.__stderr__.write("OT %s EXC %s\\n" % (${JSON.stringify(short)}, str(e)[:110]))
sys.__stderr__.flush()
`;
    const re = new RegExp('OT ' + short.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + ' (ok=|EXC)');
    const r = await runAwait(p, py, re, PER);
    if (r.dead) { console.log(`${short}  PAGE DIED`); break; }
    if (r.timeout) { console.log(`${short}  *** HUNG (no result in ${PER / 1000}s) ***`); continue; }
    for (const l of (r.log.match(/OT [^\n]*/g) || [])) {
      if (printed.has(l)) continue;
      printed.add(l);
      if (!l.includes('ok=yes')) console.log(l.replace(/^OT /, ''));
    }
  }
  console.log('DONE');
  await b.close().catch(() => {}); process.exit(0);
})().catch((e) => { console.log('DRIVER ' + String(e).slice(0, 200)); process.exit(0); });
