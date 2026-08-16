// Every workbench's declared toolbar items, checked against the registered commands.
//
// A toolbar item naming a command that was never registered is a button the user can see
// and click to no effect -- the same failure class as CAM's dead first activation, one
// level down. Menus are checked the same way where the workbench exposes them.
//
// Usage: node scratchpad/wbcommands.js [url]
const puppeteer = require('puppeteer-core');
const CHROME = process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';  // set CHROME_PATH to run off macOS
const sl = (ms) => new Promise((r) => setTimeout(r, ms));
const URL = process.argv[2] || 'http://localhost:8792/index.html';

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
    protocolTimeout: 3600000, userDataDir: '/tmp/fc-wbcmd' });
  const p = (await b.pages())[0];
  await p.goto(URL, { waitUntil: 'domcontentloaded', timeout: 300000 });
  const t0 = Date.now();
  while (Date.now() - t0 < 300000) {
    if (await p.evaluate(() => !!(window.fcInstance && window.fcInstance._malloc))) break;
    await sl(1000);
  }
  let names = [];
  for (let i = 0; i < 60; i++) {
    await sl(3000);
    const r = await runAwait(p, `
import sys, FreeCADGui as Gui
sys.__stderr__.write("WC LIST " + ",".join(Gui.listWorkbenches()) + "|END\\n"); sys.__stderr__.flush()
`, /WC LIST ([^\n|]*)\|END/, 8000);
    if (r.m && r.m[1]) { names = r.m[1].split(',').filter(Boolean); break; }
  }
  console.log(`PLAN ${names.length} workbenches`);

  let totalItems = 0, totalMissing = 0;
  for (const w of names) {
    const py = `
import sys
import FreeCADGui as Gui
name = ${JSON.stringify(w)}
try:
    if Gui.activeWorkbench().name() != name:
        Gui.activateWorkbench(name)
    wb = Gui.activeWorkbench()
    known = set(Gui.listCommands())
    items, missing = 0, []
    try:
        tb = wb.getToolbarItems()
    except Exception:
        tb = {}
    for bar, cmds in tb.items():
        for c in cmds:
            if not c or c.lower().startswith("separator"):
                continue
            items += 1
            if c not in known:
                missing.append(bar + "/" + c)
    sys.__stderr__.write("WC %s items=%d missing=%d %s\\n" % (
        name, items, len(missing), (";".join(missing[:6]) if missing else "")))
except Exception as e:
    sys.__stderr__.write("WC %s EXC %s\\n" % (name, str(e)[:110]))
sys.__stderr__.flush()
`;
    const re = new RegExp('WC ' + w + ' (items=|EXC)');
    const r = await runAwait(p, py, re, 120000);
    if (r.dead) { console.log(`${w.padEnd(24)} PAGE DIED`); break; }
    if (r.timeout) { console.log(`${w.padEnd(24)} TIMEOUT`); continue; }
    const line = (r.log.match(new RegExp('WC ' + w + ' [^\\n]*', 'g')) || []).pop() || '';
    const mi = line.match(/items=(\d+) missing=(\d+)\s*(.*)$/);
    if (mi) {
      totalItems += Number(mi[1]); totalMissing += Number(mi[2]);
      const flag = Number(mi[2]) ? `  MISSING: ${mi[3]}` : '';
      console.log(`${w.padEnd(24)} items=${mi[1].padEnd(4)} missing=${mi[2]}${flag}`);
    } else {
      console.log(`${w.padEnd(24)} ${line.replace('WC ' + w + ' ', '')}`);
    }
  }
  console.log(`TOTAL toolbar items=${totalItems} missing=${totalMissing}`);
  await b.close().catch(() => {}); process.exit(0);
})().catch((e) => { console.log('DRIVER ' + String(e).slice(0, 200)); process.exit(0); });
