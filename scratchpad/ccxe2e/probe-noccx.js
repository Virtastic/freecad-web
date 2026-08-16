// Stepwise probe: run small Python snippets one at a time so a rejection can be pinned
// to a single step instead of a 60-line script. Each step prints its own marker.
const puppeteer = require('puppeteer-core');
const fs = require('fs');
const CHROME = process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';  // set CHROME_PATH to run off macOS
const sl = (ms) => new Promise((r) => setTimeout(r, ms));

const STEPS = [
  ['A1', 'import FreeCAD\nsay("gui=%r" % FreeCAD.GuiUp)'],
  ['A2', 'd=FreeCAD.newDocument("t")\nsay("doc ok")'],
  ['A3', 'b=d.addObject("Part::Box","Box")\nsay("obj ok")'],
  ['A4', 'b.Length=100\nsay("prop ok")'],
  ['A5', 'd.recompute()\nsay("recompute ok vol=%.1f" % b.Shape.Volume)'],
];

const PRE = 'import sys\n'
  + 'def say(m):\n'
  + '    sys.__stderr__.write("PB-%s " % TAG + str(m) + "\\n"); sys.__stderr__.flush()\n'
  + 'try:\n';
const POST = '\n    say("done")\n'
  + 'except Exception as _e:\n'
  + '    import traceback\n'
  + '    say("EXC %s" % _e)\n'
  + '    say("TB " + traceback.format_exc().splitlines()[-1])\n';

function wrap(tag, body) {
  const indented = body.split('\n').map((l) => '    ' + l).join('\n');
  return 'TAG = "' + tag + '"\n' + PRE + indented + POST;
}

(async () => {
  const b = await puppeteer.launch({
    executablePath: CHROME, headless: false, defaultViewport: null,
    args: ['--no-sandbox', '--use-gl=angle', '--use-angle=metal',
           '--enable-features=SharedArrayBuffer', '--window-size=1300,850'],
    protocolTimeout: 2400000, userDataDir: '/tmp/fc-probe-noccx',
  });
  const p = (await b.pages())[0];
  const rejects = [];
  await p.exposeFunction('__note', (s) => rejects.push(String(s).slice(0, 300)));
  await p.evaluateOnNewDocument(() => {
    window.addEventListener('unhandledrejection', (e) => {
      window.__note('UNHANDLED ' + (e.reason && e.reason.message ? e.reason.message : e.reason));
    });
  });

  await p.goto('http://localhost:8796/index.html', { waitUntil: 'domcontentloaded', timeout: 300000 });
  const t0 = Date.now();
  while (Date.now() - t0 < 300000) {
    if (await p.evaluate(() => !!(window.fcInstance && window.fcInstance._malloc))) break;
    await sl(500);
  }
  await sl(12000);

  // globals must persist across snippets, so everything runs in __main__
  const results = [];
  for (const [tag, body] of STEPS) {
    const code = wrap(tag, body);
    await p.evaluate((c) => {
      const m = window.fcInstance;
      const n = new TextEncoder().encode(c).length + 1;
      const q = m._malloc(n);
      m.stringToUTF8(c, q, n);
      (window.fcRunPy || ((mm, pp) => { mm._fcweb_run_python(pp); mm._free(pp); }))(m, q);
    }, code);
    const t1 = Date.now(); let got = '';
    while (Date.now() - t1 < 600000) {
      const txt = await p.evaluate(() => {
        const e = document.getElementById('log'); return e ? e.textContent : '';
      });
      const lines = txt.split('\n').filter((l) => l.includes('PB-' + tag));
      if (lines.length) { got = lines.join(' | '); break; }
      await sl(2000);
    }
    results.push(tag + ': ' + (got || '(no output - rejected or hung)'));
    if (!got) break;
  }
  const out = results.join('\n') + '\n--- rejections ---\n' + rejects.slice(0, 6).join('\n');
  fs.writeFileSync('/tmp/probe-noccx.txt', out);
  console.log(out);
  await b.close().catch(() => {});
  process.exit(0);
})().catch((e) => {
  fs.writeFileSync('/tmp/probe-noccx.txt', 'DRIVER ' + String(e).slice(0, 300));
  process.exit(0);
});
