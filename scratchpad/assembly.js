// A multi-file (App::Link) assembly has to open in the browser, children and all.
//
// Reported 2026-09-22: opening the master of a linked assembly gave one
//   "Exception opening file: /home/web_user/_up/<child>.FCStd ... does not exist!"
// per child, because the picker took ONE file and flattened its name into the staging
// directory, so the children FreeCAD resolves relative to the master were never there.
//
// This harness builds a real linked assembly with FreeCAD itself (a master that links a
// part beside it and a second part in a subfolder), reads the files back out of the wasm
// filesystem, then starts a FRESH session and checks:
//   1. the old behaviour still fails the same way (one file, links unresolved)
//   2. staging the whole set, folders kept, opens the master with every link resolved
//   3. the staging path refuses to escape its directory
//
//   node scratchpad/assembly.js [url]
const puppeteer = require('puppeteer-core');
const sl = (ms) => new Promise((r) => setTimeout(r, ms));
const NL = String.fromCharCode(10);
const URL = process.argv[2] || 'http://127.0.0.1:8792/freecad-gui.html';
const CHROME = process.env.CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe';
let fails = 0;
const ok = (c, m) => { console.log((c ? '  ok   ' : '  FAIL ') + m); if (!c) fails++; };
const runPy = (p, c) => p.evaluate((c) => { const m = window.fcInstance; const n = new TextEncoder().encode(c).length + 1; const q = m._malloc(n); m.stringToUTF8(c, q, n); (window.fcRunPy)(m, q); }, c);
const waitFile = async (p, f, ms) => {
  const t = Date.now();
  while (Date.now() - t < ms) {
    const s = await p.evaluate((f) => { try { return window.fcInstance.FS.readFile(f, { encoding: 'utf8' }); } catch (e) { return null; } }, f);
    if (s) return s;
    await sl(1200);
  }
  return null;
};
const J = (s) => { try { return JSON.parse(s); } catch (e) { return null; } };
const boot = async (b) => {
  const p = (await b.pages())[0];
  await p.goto(URL, { waitUntil: 'domcontentloaded', timeout: 300000 });
  const t = Date.now();
  while (Date.now() - t < 420000) { if (await p.evaluate(() => !!window.__fcWorkReady && !!(window.fcInstance && window.fcInstance._malloc))) break; await sl(1500); }
  await sl(8000);
  return p;
};

// Build the fixture: master.FCStd links Part_A.FCStd (beside it) and parts/Part_B.FCStd.
const MAKE = [
  'import FreeCAD as App, os, json, traceback',
  'try:',
  '    root = "/tmp/asmfix"',
  '    os.makedirs(root + "/parts", exist_ok=True)',
  '    a = App.newDocument("Part_A")',
  '    ba = a.addObject("Part::Box", "BoxA"); ba.Length = 10; ba.Width = 10; ba.Height = 10',
  '    a.recompute(); a.saveAs(root + "/Part_A.FCStd")',
  '    b = App.newDocument("Part_B")',
  '    bb = b.addObject("Part::Cylinder", "CylB"); bb.Radius = 5; bb.Height = 20',
  '    b.recompute(); b.saveAs(root + "/parts/Part_B.FCStd")',
  '    m = App.newDocument("master")',
  '    m.saveAs(root + "/master.FCStd")   # an external link needs its owner saved first',
  '    la = m.addObject("App::Link", "LinkA"); la.LinkedObject = ba',
  '    lb = m.addObject("App::Link", "LinkB"); lb.LinkedObject = bb',
  '    lb.Placement.Base = App.Vector(30, 0, 0)',
  '    m.recompute(); m.save()',
  '    for d in (m, a, b): App.closeDocument(d.Name)',
  '    files = []',
  '    for dirpath, _dirs, names in os.walk(root):',
  '        for n in names:',
  '            full = os.path.join(dirpath, n)',
  '            if n.endswith(".FCBak"): continue   # FreeCAD keeps a backup beside the file',
  '            files.append({"rel": os.path.relpath(full, root).replace(os.sep, "/"), "size": os.path.getsize(full)})',
  '    open("/tmp/asm-made.json", "w").write(json.dumps(sorted(files, key=lambda f: f["rel"])))',
  'except Exception:',
  '    open("/tmp/asm-made.json", "w").write(json.dumps({"exc": traceback.format_exc()}))',
].join(NL);

// What the master looks like once opened: links resolved, or dangling.
const INSPECT = [
  'import FreeCAD as App, json',
  'o = {"docs": sorted(App.listDocuments().keys())}',
  'm = App.listDocuments().get("master")',
  'if m:',
  '    o["file"] = m.FileName',
  '    o["links"] = []',
  '    for obj in m.Objects:',
  '        if obj.isDerivedFrom("App::Link"):',
  '            lo = obj.LinkedObject',
  '            o["links"].append({"name": obj.Name, "target": (lo.Document.Name + "#" + lo.Name) if lo else None,',
  '                               "shape": (lo.Shape.Volume if lo and hasattr(lo, "Shape") else None)})',
  'open("/tmp/asm-state.json", "w").write(json.dumps(o))',
].join(NL);

(async () => {
  // ---- make the fixture in one session, carry the bytes out
  let b = await puppeteer.launch({ executablePath: CHROME, headless: true, defaultViewport: { width: 1400, height: 900 },
    args: ['--no-sandbox', '--use-gl=angle'], protocolTimeout: 900000, userDataDir: 'C:/Users/MICHAE~1/AppData/Local/Temp/fc-asm-a-' + Date.now() });
  let p = await boot(b);
  await runPy(p, MAKE);
  const made = J(await waitFile(p, '/tmp/asm-made.json', 120000)) || [];
  console.log('  fixture: ' + JSON.stringify(made).slice(0, 600));
  ok(Array.isArray(made) && made.length === 3, 'built a 3-file linked assembly with FreeCAD itself');
  if (!Array.isArray(made) || made.length !== 3) { await b.close(); process.exit(1); }
  const bytes = {};
  for (const f of made) {
    bytes[f.rel] = await p.evaluate((rel) => {
      const d = window.fcInstance.FS.readFile('/tmp/asmfix/' + rel);
      let s = ''; for (let i = 0; i < d.length; i++) s += String.fromCharCode(d[i]);
      return btoa(s);
    }, f.rel);
  }
  await b.close();

  // ---- fresh session: the old single-file path, then the fix
  b = await puppeteer.launch({ executablePath: CHROME, headless: true, defaultViewport: { width: 1400, height: 900 },
    args: ['--no-sandbox', '--use-gl=angle'], protocolTimeout: 900000, userDataDir: 'C:/Users/MICHAE~1/AppData/Local/Temp/fc-asm-b-' + Date.now() });
  p = await boot(b);
  const put = async (files) => p.evaluate((files) => {
    const list = files.map(f => {
      const bin = atob(f.b64); const u = new Uint8Array(bin.length);
      for (let i = 0; i < bin.length; i++) u[i] = bin.charCodeAt(i);
      return { rel: f.rel, bytes: u };
    });
    return window.__fcStageFiles(list);
  }, files);

  // 1. master alone, the way the picker used to behave
  const alone = await put([{ rel: 'master.FCStd', b64: bytes['master.FCStd'] }]);
  console.log('  staged alone: ' + JSON.stringify(alone));
  await runPy(p, 'import FreeCAD\ntry:\n FreeCAD.openDocument("/home/web_user/_up/master.FCStd")\nexcept Exception as e:\n pass');
  await sl(6000);
  await runPy(p, INSPECT);
  const lonely = J(await waitFile(p, '/tmp/asm-state.json', 60000)) || {};
  console.log('  one file only: ' + JSON.stringify(lonely));
  const dangling = (lonely.links || []).filter(l => !l.target).length;
  ok(dangling === 2, 'with only the master staged, both links are unresolved (the reported bug): ' + dangling);

  // 2. the whole set, folders preserved
  await runPy(p, [
    'import FreeCAD',
    'for d in list(FreeCAD.listDocuments().values()): FreeCAD.closeDocument(d.Name)',
    'import os',
    'os.remove("/tmp/asm-state.json")',
  ].join(NL));
  await sl(3000);
  const all = await put(Object.keys(bytes).map(rel => ({ rel: 'asmfix/' + rel, b64: bytes[rel] })));
  console.log('  staged folder: ' + JSON.stringify(all));
  ok(all.length === 3 && all.some(x => x.indexOf('/asmfix/parts/Part_B.FCStd') > 0),
     'the subfolder survives staging: ' + JSON.stringify(all.map(x => x.replace('/home/web_user/_up/', ''))));
  const master = await p.evaluate((paths) => window.__fcPickMaster(paths), all);
  ok(/asmfix\/master\.FCStd$/.test(master), 'the master is picked out of the set: ' + master);
  await runPy(p, 'import FreeCAD, FreeCADGui as Gui\nFreeCAD.openDocument(' + JSON.stringify(master) + ')\nGui.updateGui()');
  await sl(8000);
  await runPy(p, INSPECT);
  const full = J(await waitFile(p, '/tmp/asm-state.json', 90000)) || {};
  console.log('  whole folder: ' + JSON.stringify(full));
  const good = (full.links || []).filter(l => l.target && l.shape > 0);
  ok(good.length === 2, 'both links resolve to real geometry: ' + JSON.stringify((full.links || []).map(l => l.target + ' vol=' + l.shape)));
  ok((full.docs || []).length === 3, 'FreeCAD opened the children by itself: ' + JSON.stringify(full.docs));

  // 3. staging cannot escape
  const escaped = await p.evaluate(() => window.__fcStageFiles([{ rel: '../../etc/evil.txt', bytes: new Uint8Array([1, 2, 3]) }]));
  console.log('  escape attempt: ' + JSON.stringify(escaped));
  ok(escaped.every(x => x.indexOf('/home/web_user/_up/') === 0), 'a path trying to climb out stays inside the staging directory');

  await b.close();
  console.log(fails ? `${NL}${fails} FAILED` : `${NL}all passed`);
  process.exit(fails ? 1 : 0);
})();
