// Does the Assembly example stay together when FreeCAD solves it? (user report: dragging a
// part makes the excavator fly apart). Records every part's placement, runs the assembly's
// own solve, and reports which parts moved and what the solver returned.
//   node scratchpad/asmsolve.js [url]
const puppeteer = require('puppeteer-core');
const sl = (ms) => new Promise((r) => setTimeout(r, ms));
const NL = String.fromCharCode(10);
const URL = process.argv[2] || 'https://freecad.virtastic.app/';
const runPy = (p, c) => p.evaluate((c) => { const m = window.fcInstance; const n = new TextEncoder().encode(c).length + 1; const q = m._malloc(n); m.stringToUTF8(c, q, n); window.fcRunPy(m, q); }, c);
const ask = async (p, code, f, wait) => {
  for (let i = 0; i < 8; i++) {
    await p.evaluate((f) => { try { window.fcInstance.FS.unlink(f); } catch (e) {} }, f);
    await runPy(p, code); await sl(wait || 3000);
    const r = await p.evaluate((f) => { try { return window.fcInstance.FS.readFile(f, { encoding: 'utf8' }); } catch (e) { return null; } }, f);
    if (r) return r;
  }
  return null;
};
(async () => {
  const b = await puppeteer.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: true, args: ['--no-sandbox', '--use-gl=angle'], defaultViewport: { width: 1400, height: 900 }, protocolTimeout: 900000, userDataDir: 'C:/Users/MICHAE~1/AppData/Local/Temp/fc-as-' + Date.now() });
  const p = (await b.pages())[0];
  const logs = [];
  p.on('console', (m) => { const t = m.text(); if (/solv|ondsel|assembly|joint|error|exception/i.test(t)) logs.push(t.slice(0, 300)); });
  await p.goto(URL, { waitUntil: 'domcontentloaded', timeout: 300000 });
  const t = Date.now();
  while (Date.now() - t < 420000) { if (await p.evaluate(() => !!window.__fcWorkReady && !!(window.fcInstance && window.fcInstance._malloc))) break; await sl(1500); }
  await sl(8000);
  const r = await ask(p, ['import FreeCAD as App, FreeCADGui as Gui, glob, json, traceback', 'out = {}', 'try:',
    '    d = App.openDocument([x for x in glob.glob("/freecad/share/examples/*ssembly*")][0])',
    '    a = d.getObject("Assembly")',
    '    parts = [o for o in a.OutList if hasattr(o, "Placement") and o.TypeId in ("App::Link", "Part::Feature", "PartDesign::Body", "App::Part")]',
    '    P = lambda: {o.Name: [round(v, 3) for v in (o.Placement.Base.x, o.Placement.Base.y, o.Placement.Base.z)] for o in parts}',
    '    before = P()',
    '    out["solve_rc"] = a.solve()',
    '    d.recompute()',
    '    after = P()',
    '    out["moved"] = {k: (before[k], after[k]) for k in before if max(abs(x - y) for x, y in zip(before[k], after[k])) > 0.01}',
    '    out["nparts"] = len(parts)',
    '    out["joints"] = [(j.Name, getattr(j, "JointType", "?")) for j in d.Objects if j.TypeId == "App::FeaturePython" and hasattr(j, "JointType")][:40]',
    'except Exception:', '    out["exc"] = traceback.format_exc()[-800:]',
    'open("/tmp/as.json","w").write(json.dumps(out))'].join(NL), '/tmp/as.json', 8000);
  console.log(r);
  console.log('logs: ' + JSON.stringify(logs.slice(0, 10)));
  await b.close();
})();
