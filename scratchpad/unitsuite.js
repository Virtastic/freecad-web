// Run FreeCAD's OWN registered unit suites (FreeCAD.__unit_test__) in the browser.
// Upstream's definition of correct, so it is the strongest 1:1 evidence available.
//
// node drives the loop, ONE suite per _fcweb_run_python call, because that call blocks
// the page's main thread until it returns: a single call running all 34 suites would let
// nothing read the log until the end, and a trap would take the whole run's output with
// it. One call per suite means every finished suite is already reported, and a suite that
// kills the page names itself.
//
// Usage: node scratchpad/unitsuite.js [url] [only-substring]
const puppeteer = require('puppeteer-core');
const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const sl = (ms) => new Promise((r) => setTimeout(r, ms));
const URL = process.argv[2] || 'http://localhost:8792/index.html';
const ONLY = process.argv[3] || '';

const run = (p, code) => p.evaluate((c) => {
  const m = window.fcInstance;
  const n = new TextEncoder().encode(c).length + 1; const q = m._malloc(n); m.stringToUTF8(c, q, n);
  (window.fcRunPy || ((mm, pp) => { mm._fcweb_run_python(pp); mm._free(pp); }))(m, q);
}, code);

const readLog = (p) => p.evaluate(() => document.getElementById('log').textContent);

// fcRunPy hands the code to the bridge and returns; it does NOT wait for the interpreter
// to finish (there is a busy-guard/queue behind it). Reading the log straight after a
// run() therefore sees the state from BEFORE the call -- which silently reads as "no
// output" and, when the call was the suite enumeration, as "0 suites to run". Every call
// must wait for its own marker.
async function runAwait(p, code, re, timeoutMs) {
  await run(p, code);
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    await sl(2000);
    let log;
    try { log = await readLog(p); } catch (e) { return { dead: String(e).slice(0, 120) }; }
    const m = log.match(re);
    if (m) return { log, m };
  }
  return { timeout: true };
}

const suitePy = (name) => `
import sys, unittest
def say(m):
    sys.__stderr__.write("TS " + m + "\\n"); sys.__stderr__.flush()
n = ${JSON.stringify(name)}
try:
    suite = unittest.defaultTestLoader.loadTestsFromName(n)
    res = unittest.TextTestRunner(stream=open("/dev/null", "w"), verbosity=0).run(suite)
    say("%-26s run=%-4d fail=%-3d err=%-3d skip=%d" % (n, res.testsRun,
        len(res.failures), len(res.errors), len(getattr(res, "skipped", []))))
    for who, tb in (list(res.failures) + list(res.errors))[:4]:
        say("    %s | %s" % (str(who).split(" ")[0][:40], tb.strip().splitlines()[-1][:100]))
except Exception as e:
    say("%-26s LOAD-EXC %s" % (n, str(e)[:110]))
`;

(async () => {
  const b = await puppeteer.launch({ executablePath: CHROME, headless: false, defaultViewport: null,
    args: ['--no-sandbox', '--use-gl=angle', '--use-angle=metal', '--window-size=1300,850'],
    protocolTimeout: 3600000, userDataDir: '/tmp/fc-unitsuite' });
  const p = (await b.pages())[0];
  const pageErrs = [];
  p.on('pageerror', (e) => pageErrs.push(String(e).slice(0, 160)));
  await p.goto(URL, { waitUntil: 'domcontentloaded', timeout: 300000 });
  const t0 = Date.now();
  while (Date.now() - t0 < 300000) {
    if (await p.evaluate(() => !!(window.fcInstance && window.fcInstance._malloc))) break;
    await sl(1000);
  }
  // Gate on a real Python round-trip, never a timer: fcRunPy is a silent no-op until the
  // interpreter exists, and a cold profile takes far longer than any fixed sleep.
  let ready = false;
  for (let i = 0; i < 60 && !ready; i++) {
    await sl(3000);
    try {
      // Not just "python answers": each module registers its suites from its Init.py
      // during startup, so an early round-trip sees an EMPTY registry and the run plans
      // zero suites. Wait for the registry to fill.
      const r = await runAwait(p, 'import sys, FreeCAD\n'
        + 'sys.__stderr__.write("TS PYREADY %d\\n" % len(FreeCAD.__unit_test__)); sys.__stderr__.flush()\n',
        /TS PYREADY (\d+)/, 8000);
      const mm = r.log ? [...r.log.matchAll(/TS PYREADY (\d+)/g)].pop() : null;
      ready = !!mm && Number(mm[1]) > 0;
    } catch (e) { /* still booting */ }
  }
  if (!ready) { console.log('DRIVER python never became ready'); await b.close().catch(() => {}); process.exit(0); }

  const nres = await runAwait(p, `
import sys, FreeCAD
only = ${JSON.stringify(ONLY)}
ns = [n for n in FreeCAD.__unit_test__ if (not only or only in n)]
sys.__stderr__.write("TS NAMES " + ",".join(ns) + "|END\\n"); sys.__stderr__.flush()
`, /TS NAMES ([^\n|]*)\|END/, 30000);
  const names = nres.m ? nres.m[1].split(',').filter(Boolean) : [];
  console.log('PLAN ' + names.length + ' suites');

  // Track printed lines by CONTENT, not by index: the page's log is a trimming ring
  // buffer, so an index into it silently skips results once it starts dropping old
  // lines -- entire suites went unreported that way.
  const printed = new Set(nres.log.match(/TS [^\n]*/g) || []);
  const results = [];
  for (const name of names) {
    const started = Date.now();
    // each suite ends by logging a line that starts with its own name
    const done = new RegExp('TS ' + name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + ' +(run=|LOAD-EXC)');
    const r = await runAwait(p, suitePy(name), done, 900000);
    if (r.dead) { console.log(`${name.padEnd(26)} PAGE DIED: ${r.dead}`); break; }
    if (r.timeout) { console.log(`${name.padEnd(26)} TIMEOUT after 900s`); results.push(`${name} TIMEOUT`); continue; }
    for (const l of (r.log.match(/TS [^\n]*/g) || [])) {
      if (printed.has(l)) continue;
      printed.add(l);
      const out = l.replace(/^TS /, '') + (l.includes('run=') ? `  [${((Date.now() - started) / 1000).toFixed(1)}s]` : '');
      console.log(out);
      results.push(out);
    }
  }
  console.log('--- summary ---');
  for (const l of results) console.log(l);
  console.log('PAGEERRS ' + pageErrs.length + (pageErrs.length ? ' :: ' + pageErrs.slice(0, 3).join(' | ') : ''));
  await p.screenshot({ path: '/tmp/unitsuite.png' }).catch(() => {});
  await b.close().catch(() => {}); process.exit(0);
})().catch((e) => { console.log('DRIVER ' + String(e).slice(0, 200)); process.exit(0); });
