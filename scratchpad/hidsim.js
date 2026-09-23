// The page's WebHID 3D-mouse path, end to end minus the browser's HID stack (GitHub #2).
// navigator.hid.requestDevice is replaced by a fake device that delivers real SpaceMouse
// report bytes (id 1: tx,ty,tz,rx,ry,rz as int16 LE, 12 bytes, what high-speed devices
// and the Universal Receiver send), so the parsing, the export calls and FreeCAD's
// navigation all run for real. A second, silent device must produce the driver warning.
//   node scratchpad/hidsim.js [url]
const puppeteer = require('puppeteer-core');
const sl = (ms) => new Promise((r) => setTimeout(r, ms));
const NL = String.fromCharCode(10);
const URL = process.argv[2] || 'http://127.0.0.1:8792/freecad-gui.html';
let fails = 0;
const ok = (c, m) => { console.log((c ? '  ok   ' : '  FAIL ') + m); if (!c) fails++; };
const runPy = (p, c) => p.evaluate((c) => { const m = window.fcInstance; const n = new TextEncoder().encode(c).length + 1; const q = m._malloc(n); m.stringToUTF8(c, q, n); window.fcRunPy(m, q); }, c);
const cam = async (p) => {
  for (let i = 0; i < 6; i++) {
    await p.evaluate(() => { try { window.fcInstance.FS.unlink('/tmp/c.txt'); } catch (e) {} });
    await runPy(p, 'import FreeCADGui as Gui' + NL + 'open("/tmp/c.txt","w").write(Gui.ActiveDocument.ActiveView.getCamera().split("orientation")[1][:60])');
    await sl(2000);
    const r = await p.evaluate(() => { try { return window.fcInstance.FS.readFile('/tmp/c.txt', { encoding: 'utf8' }); } catch (e) { return null; } });
    if (r) return r;
  }
  return null;
};
(async () => {
  const b = await puppeteer.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: true, args: ['--no-sandbox', '--use-gl=angle'], defaultViewport: { width: 1400, height: 900 }, protocolTimeout: 900000, userDataDir: 'C:/Users/MICHAE~1/AppData/Local/Temp/fc-hid-' + Date.now() });
  const p = (await b.pages())[0];
  const logs = [];
  p.on('console', (m) => { if (/3D mouse/.test(m.text())) logs.push(m.text()); });
  await p.goto(URL, { waitUntil: 'domcontentloaded', timeout: 300000 });
  const t = Date.now();
  while (Date.now() - t < 420000) { if (await p.evaluate(() => !!window.__fcWorkReady && !!(window.fcInstance && window.fcInstance._malloc))) break; await sl(1500); }
  await sl(8000);
  await runPy(p, ['import FreeCAD as App, FreeCADGui as Gui', 'd = App.newDocument("H")', 'd.addObject("Part::Box", "B")', 'd.recompute()', 'v = Gui.ActiveDocument.ActiveView', 'v.viewIsometric(); v.fitAll()'].join(NL));
  await sl(4000);
  await p.mouse.click(800, 600); await sl(800);   // focus the 3D view, as a user does
  // a fake WebHID device
  await p.evaluate((silent) => {
    const mk = (name, pid) => { const d = new EventTarget(); Object.assign(d, { productName: name, vendorId: 0x256f, productId: pid, opened: false, collections: [{ usagePage: 1, usage: 8, inputReports: [{ reportId: 1 }, { reportId: 3 }] }] }); d.open = async () => { d.opened = true; }; return d; };
    window.__fakeDev = mk('3Dconnexion Universal Receiver', 0xc652);
    navigator.hid.requestDevice = async () => [window.__fakeDev];
  });
  const before = await cam(p);
  const connected = await p.evaluate(() => window.fcwebSpaceballConnect());
  ok(connected === true, 'fcwebSpaceballConnect opens the device');
  await p.evaluate(async () => {
    for (let i = 0; i < 30; i++) {
      const dv = new DataView(new ArrayBuffer(12));
      [0, 0, 0, 0, 0, 350].forEach((v, k) => dv.setInt16(k * 2, v, true));
      const e = new Event('inputreport'); e.reportId = 1; e.data = dv; e.device = window.__fakeDev;
      window.__fakeDev.dispatchEvent(e);
      await new Promise((r) => setTimeout(r, 8));
    }
    const dv = new DataView(new ArrayBuffer(12)); const e = new Event('inputreport'); e.reportId = 1; e.data = dv; window.__fakeDev.dispatchEvent(e);
  });
  await sl(3000);
  const after = await cam(p);
  console.log('  camera ' + before + ' -> ' + after);
  ok(before && after && before !== after, 'report-1 rotation from the device turns the view');
  ok(logs.some((l) => /opened: 3Dconnexion Universal Receiver 256f:c652/.test(l)) && logs.some((l) => /first report id=1 bytes=12/.test(l)), 'the console says what was opened and what arrived');
  // a silent device: paired, never reports
  const warned = await p.evaluate(async () => {
    const d = new EventTarget(); Object.assign(d, { productName: 'Silent Receiver', vendorId: 0x256f, productId: 0xc652, opened: false, collections: [] }); d.open = async () => { d.opened = true; };
    navigator.hid.requestDevice = async () => [d];
    await window.fcwebSpaceballConnect();
    await new Promise((r) => setTimeout(r, 16500));
    return document.body.innerText.indexOf('keeps the device to itself') >= 0;
  });
  ok(warned, 'a paired device that sends nothing gets an explanation, not silence');
  await b.close();
  console.log(fails ? fails + ' FAILED' : 'all passed');
  process.exit(fails ? 1 : 0);
})();
