// The 3Dconnexion driver path (GitHub #2), without a driver. 3dx/3dconnexion.min.js is
// replaced by a stand-in that plays the driver's side of navlib the way the real client
// does: connect -> onConnect -> create3dmouse -> on3dmouseCreated, then property reads and
// writes through the client's callbacks. That exercises the page's client and the engine's
// fcweb_nl_* exports for real: the camera read back, a rotated camera written, the model
// extents, and a hit test. A second run serves the REAL client with no driver present and
// must fall through to the WebHID chooser without errors.
//   node scratchpad/navlibsim.js [url]
const puppeteer = require('puppeteer-core');
const sl = (ms) => new Promise((r) => setTimeout(r, ms));
const NL = String.fromCharCode(10);
const URL = process.argv[2] || 'http://127.0.0.1:8792/freecad-gui.html';
let fails = 0;
const ok = (c, m) => { console.log((c ? '  ok   ' : '  FAIL ') + m); if (!c) fails++; };
const STANDIN = `window._3Dconnexion = function (client) {
  window.__nlClient = client; this.client = client;
  this.connect = function () { var c = client; setTimeout(function () { c.onConnect(); }, 50); return 1; };
  this.create3dmouse = function () { var c = client; setTimeout(function () { c.on3dmouseCreated(); }, 50); };
  this.update3dcontroller = function (v) { (window.__nlUpdates = window.__nlUpdates || []).push(Object.keys(v)); return Promise.resolve(0); };
};`;
const runPy = (p, c) => p.evaluate((c) => { const m = window.fcInstance; const n = new TextEncoder().encode(c).length + 1; const q = m._malloc(n); m.stringToUTF8(c, q, n); window.fcRunPy(m, q); }, c);
const boot = async (standin) => {
  const b = await puppeteer.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: true, args: ['--no-sandbox', '--use-gl=angle'], defaultViewport: { width: 1400, height: 900 }, protocolTimeout: 900000, userDataDir: 'C:/Users/MICHAE~1/AppData/Local/Temp/fc-nl-' + Date.now() });
  const p = (await b.pages())[0];
  const errs = [];
  p.on('pageerror', (e) => errs.push(String(e.message || e).slice(0, 200)));
  if (standin) {
    await p.setRequestInterception(true);
    p.on('request', (r) => {
      if (/\/3dx\/3dconnexion\.min\.js/.test(r.url())) return r.respond({ status: 200, contentType: 'text/javascript', headers: { 'Cross-Origin-Resource-Policy': 'same-origin' }, body: STANDIN });
      r.continue();
    });
  }
  await p.goto(URL, { waitUntil: 'domcontentloaded', timeout: 300000 });
  const t = Date.now();
  while (Date.now() - t < 420000) { if (await p.evaluate(() => !!window.__fcWorkReady && !!(window.fcInstance && window.fcInstance._malloc))) break; await sl(1500); }
  await sl(8000);
  await runPy(p, ['import FreeCAD as App, FreeCADGui as Gui', 'd = App.newDocument("N")', 'b = d.addObject("Part::Box", "B"); b.Length = 40', 'd.recompute()', 'v = Gui.ActiveDocument.ActiveView', 'v.viewIsometric(); v.fitAll()'].join(NL));
  await sl(5000);
  return { b, p, errs };
};
(async () => {
  // 1. the driver path, against the stand-in
  let { b, p, errs } = await boot(true);
  const exp = await p.evaluate(() => ['_fcweb_nl_read', '_fcweb_nl_write', '_fcweb_nl_buf', '_fcweb_nl_view_id'].map((n) => typeof window.fcInstance[n]));
  ok(exp.every((x) => x === 'function'), 'the engine exports navlib: ' + JSON.stringify(exp));
  const connected = await p.evaluate(() => window.__fc3dxDriver(3000));
  ok(connected === true, 'the page connects to the (stand-in) driver');
  const r = await p.evaluate(async () => {
    const c = window.__nlClient, o = {};
    o.affine = c.getViewMatrix(); o.persp = c.getPerspective(); o.extents = c.getViewExtents();
    o.model = c.getModelExtents(); o.rot = c.getViewRotatable(); o.cs = c.getCoordinateSystem();
    // rotate the camera 30 degrees about world Z, the way navlib writes view.affine
    const a = o.affine.slice(), ang = Math.PI / 6, cs = Math.cos(ang), sn = Math.sin(ang);
    const rotRow = (x, y, z) => [cs * x - sn * y, sn * x + cs * y, z];
    const out = a.slice();
    for (const r0 of [0, 4, 8, 12]) { const v = rotRow(a[r0], a[r0 + 1], a[r0 + 2]); out[r0] = v[0]; out[r0 + 1] = v[1]; out[r0 + 2] = v[2]; }
    o.writeRc = c.setViewMatrix(out);
    await new Promise((z) => setTimeout(z, 500));
    o.after = c.getViewMatrix();
    // hit test straight down the view axis through the model centre
    const m = o.model, ctr = [(m[0] + m[3]) / 2, (m[1] + m[4]) / 2, (m[2] + m[5]) / 2];
    // Orthographic: desktop's SetHitLookFrom starts the ray at the camera, so aim from the
    // camera at the model centre (the view axis itself can pass beside a thin box).
    const cp = [o.after[12], o.after[13], o.after[14]], dv = [ctr[0] - cp[0], ctr[1] - cp[1], ctr[2] - cp[2]];
    const dl = Math.hypot(dv[0], dv[1], dv[2]), dir = dv.map((x) => x / dl);
    c.setLookDirection(dir); c.setLookFrom([ctr[0] - dir[0] * 500, ctr[1] - dir[1] * 500, ctr[2] - dir[2] * 500]); c.setLookAperture(1); c.setSelectionOnly(false);
    o.hit = c.getLookAt();
    // zoom (orthographic): halve the extents. After the hit test on purpose: desktop's
    // SetViewExtents also records the near distance its orthographic hit ray starts from.
    const e = o.extents; o.zoomRc = c.setViewExtents(e.map((x) => x / 2)); o.extents2 = c.getViewExtents();
    o.pivot = c.setPivotPosition(ctr); o.pivotVis = c.setPivotVisible(true);
    o.updates = window.__nlUpdates;
    return o;
  });
  console.log('  camera affine before: ' + JSON.stringify(r.affine && r.affine.map((x) => +x.toFixed(3))));
  console.log('  camera affine after:  ' + JSON.stringify(r.after && r.after.map((x) => +x.toFixed(3))));
  ok(Array.isArray(r.affine) && r.affine.length === 16, 'view.affine reads a 4x4 camera');
  ok(r.writeRc === 0 && JSON.stringify(r.after.map((x) => +x.toFixed(3))) === JSON.stringify((() => { const a = r.affine, cs = Math.cos(Math.PI / 6), sn = Math.sin(Math.PI / 6), o = a.slice(); for (const r0 of [0, 4, 8, 12]) { const x = a[r0], y = a[r0 + 1]; o[r0] = cs * x - sn * y; o[r0 + 1] = sn * x + cs * y; } return o.map((x) => +x.toFixed(3)); })()),
     'writing view.affine moves FreeCAD\'s camera to exactly that pose');
  ok(r.persp === false && Array.isArray(r.extents) && r.zoomRc === 0 && Math.abs(r.extents2[3] - r.extents[3] / 2) < 1e-3 * Math.abs(r.extents[3]), 'orthographic zoom through view.extents: ' + (r.extents && r.extents[3].toFixed(2)) + ' -> ' + (r.extents2 && r.extents2[3].toFixed(2)));
  ok(Array.isArray(r.model) && r.model[3] - r.model[0] > 39, 'model.extents covers the 40 mm box: ' + JSON.stringify(r.model && r.model.map((x) => +x.toFixed(1))));
  ok(Array.isArray(r.hit) && r.hit.length === 3, 'hit testing finds the model: ' + JSON.stringify(r.hit && r.hit.map((x) => +x.toFixed(2))));
  ok(r.pivot === 0 && r.pivotVis === 0, 'the pivot marker can be placed and shown');
  ok(r.rot === true && r.cs[6] === -1, 'rotatable, and FreeCAD\'s Z-up coordinate system');
  ok((r.updates || []).some((k) => k.includes('view.affine')), 'the active view was announced to the driver: ' + JSON.stringify(r.updates));
  ok(errs.length === 0, 'no page errors: ' + JSON.stringify(errs));
  await b.close();
  // 2. the real client with no driver: must say no, quietly
  ({ b, p, errs } = await boot(false));
  const t0 = Date.now();
  const res = await p.evaluate(() => window.__fc3dxDriver(2000));
  ok(res === false && Date.now() - t0 < 6000, 'with no driver the real client gives up within the budget (' + (Date.now() - t0) + ' ms)');
  ok(errs.length === 0, 'and raises no page errors: ' + JSON.stringify(errs));
  await b.close();
  console.log(fails ? fails + ' FAILED' : 'all passed');
  process.exit(fails ? 1 : 0);
})();
