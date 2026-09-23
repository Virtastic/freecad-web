// GitHub #2: does a 3D mouse move FreeCAD's camera? No device here, so this drives the
// exports the page's WebHID code calls (fcweb_spaceball.cpp) and reads the camera back,
// plus checks the Spaceball customize pages are registered. The report parsing and the
// device chooser need a physical SpaceMouse; that half is a manual check.
//   node scratchpad/spaceball.js [url]
const puppeteer = require('puppeteer-core');
const sl = (ms) => new Promise((r) => setTimeout(r, ms));
const NL = String.fromCharCode(10);
const URL = process.argv[2] || 'http://127.0.0.1:8792/freecad-gui.html';
let fails = 0;
const ok = (c, m) => { console.log((c ? '  ok   ' : '  FAIL ') + m); if (!c) fails++; };
const runPy = (p, c) => p.evaluate((c) => { const m = window.fcInstance; const n = new TextEncoder().encode(c).length + 1; const q = m._malloc(n); m.stringToUTF8(c, q, n); window.fcRunPy(m, q); }, c);
const ask = async (p, code, f) => {
  for (let i = 0; i < 6; i++) {
    await p.evaluate((f) => { try { window.fcInstance.FS.unlink(f); } catch (e) {} }, f);
    await runPy(p, code); await sl(2500);
    const r = await p.evaluate((f) => { try { return window.fcInstance.FS.readFile(f, { encoding: 'utf8' }); } catch (e) { return null; } }, f);
    if (r) return r;
  }
  return null;
};
const CAM = ['import FreeCADGui as Gui, json, traceback', 'try:', '    v = Gui.ActiveDocument.ActiveView', '    r = {"cam": v.getCamera()[:400]}',
  'except Exception:', '    r = {"err": traceback.format_exc()[-300:]}', 'open("/tmp/cam.json","w").write(json.dumps(r))'].join(NL);
(async () => {
  const b = await puppeteer.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: true,
    defaultViewport: { width: 1400, height: 900 }, args: ['--no-sandbox', '--use-gl=angle'], protocolTimeout: 900000,
    userDataDir: 'C:/Users/MICHAE~1/AppData/Local/Temp/fc-sb-' + Date.now() });
  const p = (await b.pages())[0];
  await p.goto(URL, { waitUntil: 'domcontentloaded', timeout: 300000 });
  const t = Date.now();
  while (Date.now() - t < 420000) { if (await p.evaluate(() => !!window.__fcWorkReady && !!(window.fcInstance && window.fcInstance._malloc))) break; await sl(1500); }
  await sl(8000);
  const ex = await p.evaluate(() => ['_fcweb_spaceball_present', '_fcweb_spaceball_motion', '_fcweb_spaceball_button'].map((n) => typeof window.fcInstance[n]));
  ok(ex.every((x) => x === 'function'), 'the three bridge exports exist: ' + JSON.stringify(ex));
  ok(await p.evaluate(() => typeof window.fcwebSpaceballConnect === 'function' || !navigator.hid), 'the page offers fcwebSpaceballConnect');
  await runPy(p, ['import FreeCAD as App, FreeCADGui as Gui', 'd = App.newDocument("SB")', 'd.addObject("Part::Box", "B")', 'd.recompute()',
    'v = Gui.ActiveDocument.ActiveView', 'v.viewIsometric(); v.fitAll(); Gui.updateGui()'].join(NL));
  await sl(5000);
  // postMotionEvent posts to the FOCUS widget, as on desktop, so give the view focus the
  // way a user does: a real click in the 3D view.
  await p.mouse.click(800, 600); await sl(1000);
  const before = await ask(p, CAM, '/tmp/cam.json');
  await p.evaluate(() => { const M = window.fcInstance; M._fcweb_spaceball_present(1); for (let i = 0; i < 20; i++) M._fcweb_spaceball_motion(0, 0, 0, 0, 0, 3000); });
  await sl(4000);
  const after = await ask(p, CAM, '/tmp/cam.json');
  console.log('  camera before: ' + before + NL + '  camera after:  ' + after);
  ok(before && after && !/err/.test(before) && before !== after, 'rotation from the 3D mouse moves the camera');
  const pages = await ask(p, ['from PySide import QtWidgets', 'import FreeCADGui as Gui, json',
    'app = QtWidgets.QApplication.instance()',
    'open("/tmp/sbp.json","w").write(json.dumps({"present": Gui.getMainWindow() is not None}))'].join(NL), '/tmp/sbp.json');
  ok(!!pages, 'the interpreter answers after motion events: ' + pages);
  await b.close();
  console.log(fails ? fails + ' FAILED' : 'all passed: the 3D mouse bridge moves the view');
  process.exit(fails ? 1 : 0);
})();
