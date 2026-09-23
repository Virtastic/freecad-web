// GitHub #3: FreeCAD in an iframe, driven by the page around it. A host page (itself
// cross-origin isolated, iframe allow="cross-origin-isolated") opens a model whose Box
// length comes from a spreadsheet cell, changes the cell through postMessage, and asks
// for an STL, which must come back as bytes of the right size of solid.
//   node scratchpad/embedcheck.js [host url]
// Serve scratchpad/embedtest.html and the model from scratchpad/embed-param.py (run it in
// desktop FreeCAD) beside freecad-gui.html; scratchpad/testserver.js sends COOP/COEP.
const puppeteer = require('puppeteer-core');
const sl = (ms) => new Promise((r) => setTimeout(r, ms));
const HOST = process.argv[2] || 'http://127.0.0.1:8792/embedtest.html';
let fails = 0;
const ok = (c, m) => { console.log((c ? '  ok   ' : '  FAIL ') + m); if (!c) fails++; };
(async () => {
  const b = await puppeteer.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: true,
    defaultViewport: { width: 1100, height: 800 }, args: ['--no-sandbox', '--use-gl=angle'], protocolTimeout: 900000,
    userDataDir: 'C:/Users/MICHAE~1/AppData/Local/Temp/fc-emb-' + Date.now() });
  const p = (await b.pages())[0];
  await p.goto(HOST, { waitUntil: 'domcontentloaded' });
  const t = Date.now();
  while (Date.now() - t < 420000 && !(await p.evaluate(() => window.readyAt))) await sl(1500);
  ok(await p.evaluate(() => window.readyAt) > 0, 'the frame boots and announces ready (' + Math.round((Date.now() - t) / 1000) + ' s)');
  const ask = async (m) => {
    const id = Math.random().toString(36).slice(2); await p.evaluate((m) => window.send(m), Object.assign({ id }, m));
    for (let i = 0; i < 240; i++) { const r = await p.evaluate((id) => { const x = window.results.find((r) => r.id === id); return x ? { ok: x.ok, value: x.value, error: x.error, bytes: x.data ? x.data.byteLength : 0, head: x.data ? Array.from(new Uint8Array(x.data).slice(0, 5)) : null, size: x.data && x.data.byteLength > 84 ? (() => { const dv = new DataView(x.data), n = dv.getUint32(80, true), lo = [1e9, 1e9, 1e9], hi = [-1e9, -1e9, -1e9]; for (let t = 0; t < n; t++) for (let v = 0; v < 3; v++) for (let k = 0; k < 3; k++) { const f = dv.getFloat32(84 + t * 50 + 12 + v * 12 + k * 4, true); lo[k] = Math.min(lo[k], f); hi[k] = Math.max(hi[k], f); } return hi.map((h, k) => +(h - lo[k]).toFixed(3)); })() : null } : null; }, id); if (r) return r; await sl(500); }
    return { ok: false, error: 'no reply' };
  };
  const o = await ask({ fcweb: 'open', url: 'param.FCStd', name: 'param.FCStd' });
  ok(o.ok, 'open a parametric model by URL: ' + JSON.stringify(o));
  const s = await ask({ fcweb: 'set', sheet: 'Spreadsheet', cell: 'A1', value: '40' });
  ok(s.ok && /^40/.test(String(s.value)), 'set the driving cell to 40: ' + JSON.stringify(s));
  const v = await ask({ fcweb: 'set', object: 'Box', property: 'Height', value: 7.5 });
  ok(v.ok, 'set a property directly: ' + JSON.stringify(v));
  const x = await ask({ fcweb: 'export', format: 'stl', objects: ['Box'] });
  ok(x.ok && x.bytes > 500, 'export STL comes back as bytes: ' + x.bytes + ' bytes, starts ' + JSON.stringify(x.head));
  ok(JSON.stringify(x.size) === '[40,10,7.5]', 'the STL is the edited solid, 40 x 10 x 7.5: ' + JSON.stringify(x.size));
  const bad = await ask({ fcweb: 'set', object: 'Nope', property: 'Length', value: 1 });
  ok(!bad.ok && /Nope|NoneType|attribute/.test(bad.error || ''), 'a bad request answers with an error, not silence');
  await p.screenshot({ path: 'C:/tmp/embed.png' });
  await b.close();
  console.log(fails ? fails + ' FAILED' : 'all passed: embedding works');
  process.exit(fails ? 1 : 0);
})();
