// Can a user articulate an assembly by dragging a part? (user report, Firefox: "it pulls the
// view around"). Opens the Assembly example, activates the assembly the way a user does
// (double-click in the tree == setEdit), frames the bucket, then drags it with the REAL
// mouse and reports whether the part moved (joints solved) or the camera did.
//   node scratchpad/asmdrag.js [url]        BROWSER=chrome for the control
const puppeteer = require('puppeteer-core');
const sl = (ms) => new Promise((r) => setTimeout(r, ms));
const NL = String.fromCharCode(10);
const URL = process.argv[2] || 'https://freecad.virtastic.app/';
const FF = process.env.FIREFOX_PATH || 'C:/tmp/browsers/firefox/win64-stable_156.0.1/core/firefox.exe';
const runPy = (p, c) => p.evaluate((c) => { const m = window.fcInstance; const n = new TextEncoder().encode(c).length + 1; const q = m._malloc(n); m.stringToUTF8(c, q, n); window.fcRunPy(m, q); }, c);
const ask = async (p, code, f) => {
  for (let i = 0; i < 8; i++) {
    await p.evaluate((f) => { try { window.fcInstance.FS.unlink(f); } catch (e) {} }, f);
    await runPy(p, code); await sl(2500);
    const r = await p.evaluate((f) => { try { return window.fcInstance.FS.readFile(f, { encoding: 'utf8' }); } catch (e) { return null; } }, f);
    if (r) return JSON.parse(r);
  }
  return null;
};
const STATE = ['import FreeCAD as App, FreeCADGui as Gui, json, traceback', 'try:',
  '    d = App.ActiveDocument', '    a = d.getObject("Assembly")',
  '    parts = [o for o in a.OutList if hasattr(o, "Placement") and o.TypeId in ("App::Link", "Part::Feature", "PartDesign::Body", "App::Part")]',
  '    v = Gui.ActiveDocument.ActiveView', '    e = Gui.ActiveDocument.getInEdit()',
  '    r = {"parts": {o.Name: [round(x, 2) for x in (o.Placement.Base.x, o.Placement.Base.y, o.Placement.Base.z)] for o in parts}, "cam": v.getCamera()[60:200], "edit": type(e).__name__ if e else None}',
  'except Exception:', '    r = {"err": traceback.format_exc()[-500:]}',
  'open("/tmp/asm.json","w").write(json.dumps(r))'].join(NL);
(async () => {
  const chrome = process.env.BROWSER === 'chrome';
  const b = chrome
    ? await puppeteer.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: true, args: ['--no-sandbox', '--use-gl=angle'], defaultViewport: { width: 1400, height: 900 }, protocolTimeout: 900000, userDataDir: 'C:/Users/MICHAE~1/AppData/Local/Temp/fc-asm-' + Date.now() })
    : await puppeteer.launch({ browser: 'firefox', executablePath: FF, headless: true, defaultViewport: { width: 1400, height: 900 }, protocolTimeout: 900000 });
  const p = (await b.pages())[0];
  await p.goto(URL, { waitUntil: 'domcontentloaded', timeout: 300000 });
  const t = Date.now();
  while (Date.now() - t < 600000) { if (await p.evaluate(() => !!window.__fcWorkReady && !!(window.fcInstance && window.fcInstance._malloc))) break; await sl(2000); }
  await sl(8000);
  const navlog = [];
  p.on('console', (m) => { const t = m.text(); if (/State|isEditing|refire/.test(t)) navlog.push(t.replace(/\s+/g, ' ').slice(0, 120)); });
  await runPy(p, ['import FreeCAD as App, FreeCADGui as Gui, glob',
    ...(process.env.DEBUGNAV ? ['App.ParamGet("User parameter:BaseApp/Preferences/View").SetBool("NavigationDebug", True)'] : []),
    'd = App.openDocument([x for x in glob.glob("/freecad/share/examples/*ssembly*")][0])',
    'Gui.activateWorkbench("AssemblyWorkbench")',
    'Gui.ActiveDocument.setEdit(d.getObject("Assembly"))',
    ...(process.env.NAV ? ['Gui.ActiveDocument.ActiveView.setNavigationType(' + JSON.stringify(process.env.NAV) + ')'] : []),
    'Gui.Selection.clearSelection(); Gui.Selection.addSelection(d.Name, "Assembly", "Bucket001.")',
    'v = Gui.ActiveDocument.ActiveView', 'v.viewIsometric(); Gui.SendMsgToActiveView("ViewSelection"); Gui.Selection.clearSelection(); Gui.updateGui()'].join(NL));
  await sl(14000);
  const s0 = await ask(p, STATE, '/tmp/asm.json');
  console.log('  before: ' + JSON.stringify(s0).slice(0, 600));
  await p.screenshot({ path: 'C:/tmp/asm-before-' + (chrome ? 'chrome' : 'ff') + '.png' });
  // hover first so FreeCAD preselects the part, then press, drag, release
  const X = +(process.env.X || 545), Y = +(process.env.Y || 400);   // a point on the bucket in that window
  await p.mouse.move(X - 15, Y - 10); await sl(300);
  await p.mouse.move(X, Y, { steps: 6 }); await sl(1500);
  if (process.env.PRESELECT === '1') { await p.mouse.click(X, Y); await sl(1500); }
  if (process.env.PRESELECT === '1') {
    const sel = await ask(p, ['import FreeCADGui as Gui, json', 'x = [(s.ObjectName, list(s.SubElementNames)) for s in Gui.Selection.getSelectionEx("", 0)]', 'import FreeCADGui', 'vp = Gui.ActiveDocument.getInEdit()', 'open("/tmp/sel.json","w").write(json.dumps({"sel": x, "edit": bool(vp), "nav": Gui.ActiveDocument.ActiveView.getNavigationType()}))'].join(NL), '/tmp/sel.json');
    console.log('  after click: ' + JSON.stringify(sel));
  }
  navlog.length = 0;
  await p.mouse.down(); await sl(300);
  for (let i = 1; i <= 20; i++) { await p.mouse.move(X + i * 5, Y - i * 4); await sl(60); }
  await sl(300); await p.mouse.up(); await sl(3000);
  const s1 = await ask(p, STATE, '/tmp/asm.json');
  console.log('  after:  ' + JSON.stringify(s1).slice(0, 900));
  await p.screenshot({ path: 'C:/tmp/asm-after-' + (chrome ? 'chrome' : 'ff') + '.png' });
  if (process.env.DEBUGNAV) console.log('  nav states during drag: ' + JSON.stringify(navlog.slice(0, 30)));
  const moved = s0 && s1 && s0.parts && Object.keys(s0.parts).filter((k) => JSON.stringify(s0.parts[k]) !== JSON.stringify(s1.parts[k]));
  const spun = s0 && s1 && JSON.stringify(s0.cam) !== JSON.stringify(s1.cam);
  console.log('  assembly in edit: ' + (s0 && s0.edit) + '   parts moved: ' + JSON.stringify(moved) + '   camera moved: ' + spun);
  await b.close();
})();
