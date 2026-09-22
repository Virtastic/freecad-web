// Does freecad-web run in Firefox now?
//
// The wall was written when Chromium was the only engine with JSPI. That changed:
// Firefox shipped Memory64 in 134 and JSPI in 153 (webstatus.dev, checked 2026-09-22),
// and stable is 156. This harness answers the question with the engine itself rather
// than a support table:
//   1. the page's OWN probe (the 56-byte memory64 + JSPI module, BigInt in, Number
//      rejected) run verbatim in Firefox
//   2. cross-origin isolation and WebGL2, the wall's other two gates
//   3. whether the wall lets the page through
//   4. whether the engine actually boots and does CAD work
//
//   node scratchpad/firefox.js [url]
// Firefox comes from: npx @puppeteer/browsers install firefox@stable --path C:/tmp/browsers
const puppeteer = require('puppeteer-core');
const sl = (ms) => new Promise((r) => setTimeout(r, ms));
const NL = String.fromCharCode(10);
const URL = process.argv[2] || 'https://freecad.virtastic.app/';
const FIREFOX = process.env.FIREFOX_PATH || 'C:/tmp/browsers/firefox/win64-stable_156.0.1/core/firefox.exe';
let fails = 0;
const ok = (c, m) => { console.log((c ? '  ok   ' : '  FAIL ') + m); if (!c) fails++; };

// The page's probe, copied verbatim from play-gui/freecad-gui.html so this measures the
// same bytes the wall measures. (module: memory 1 i64; import env.wait (i64)->i64;
// export f (i64)->i64 = call wait)
const PROBE_JS = `(async () => {
  const PROBE = new Uint8Array([
    0,97,115,109,1,0,0,0, 1,6,1,96,1,126,1,126, 2,11,1,3,101,110,118,4,119,97,105,116,0,0,
    3,2,1,0, 5,4,1,4,1,1, 7,5,1,1,102,0,1, 10,8,1,6,0,32,0,16,0,11
  ]);
  const out = { validate: false, suspending: typeof WebAssembly.Suspending, promising: typeof WebAssembly.promising };
  try { out.validate = WebAssembly.validate(PROBE); } catch (e) { out.validateErr = String(e); }
  try {
    const r = await WebAssembly.instantiate(PROBE, { env: { wait: new WebAssembly.Suspending((x) => Promise.resolve(x)) } });
    const f = WebAssembly.promising(r.instance.exports.f);
    out.bigint = String(await f(BigInt(7)));
    try { const p = f(7); out.numberRejected = false; if (p && p.then) { await p; } }
    catch (e) { out.numberRejected = true; out.numberErr = String(e).slice(0, 80); }
    if (out.numberRejected === false && out.bigint === '7') out.numberRejected = 'accepted a Number (the BigInt bug)';
  } catch (e) { out.instantiateErr = String(e).slice(0, 160); }
  out.crossOriginIsolated = self.crossOriginIsolated === true;
  out.sharedArrayBuffer = typeof SharedArrayBuffer === 'function';
  try { const c = document.createElement('canvas'); out.webgl2 = !!c.getContext('webgl2'); } catch (e) { out.webgl2 = false; }
  out.ua = navigator.userAgent;
  return out;
})()`;

(async () => {
  const b = await puppeteer.launch({ browser: 'firefox', executablePath: FIREFOX, headless: true,
    defaultViewport: { width: 1400, height: 900 }, protocolTimeout: 900000,
    // memory64 + JSPI are on by default in 153+; these only matter on an older build
    extraPrefsFirefox: { 'javascript.options.wasm_memory64': true, 'javascript.options.wasm_js_promise_integration': true } });
  const p = (await b.pages())[0];
  const errors = [];
  p.on('pageerror', e => errors.push(String(e).slice(0, 200)));
  const engineReqs = [];
  p.on('request', r => { if (/FreeCAD\.(js|wasm|data)/.test(r.url())) engineReqs.push(r.url().split('/').pop()); });

  await p.goto(URL, { waitUntil: 'domcontentloaded', timeout: 300000 });
  const probe = await p.evaluate(PROBE_JS);
  console.log('  ' + probe.ua);
  console.log('  probe: ' + JSON.stringify(probe, null, 0).slice(0, 400));
  ok(probe.validate === true, 'memory64 module validates');
  ok(probe.suspending === 'function' && probe.promising === 'function', 'WebAssembly.Suspending and .promising exist');
  ok(probe.bigint === '7', 'a promising export suspends and resumes with a BigInt: ' + probe.bigint);
  ok(probe.numberRejected === true, 'a Number argument is rejected, as the app requires: ' + probe.numberRejected);
  ok(probe.crossOriginIsolated === true && probe.sharedArrayBuffer === true, 'cross-origin isolated with SharedArrayBuffer');
  ok(probe.webgl2 === true, 'WebGL2 available');

  // 3. what the wall decided
  await sl(6000);
  const wall = await p.evaluate(() => {
    const w = document.getElementById('wall');
    return { present: !!w, visible: !!w && getComputedStyle(w).display !== 'none',
             headline: w ? (w.innerText || '').split(String.fromCharCode(10))[1] : null,
             loader: !!document.getElementById('load') };
  });
  console.log('  wall: ' + JSON.stringify(wall));
  ok(!wall.visible, 'the browser wall does not block Firefox');

  // 4. does it actually boot and compute?
  const t = Date.now();
  let ready = false;
  while (Date.now() - t < 600000) {
    ready = await p.evaluate(() => !!window.__fcWorkReady && !!(window.fcInstance && window.fcInstance._malloc));
    if (ready) break;
    await sl(2000);
  }
  ok(ready, 'the engine reaches ready in Firefox (' + Math.round((Date.now() - t) / 1000) + ' s, engine files fetched: ' + engineReqs.length + ')');
  if (ready) {
    await sl(6000);
    await p.evaluate((c) => { const m = window.fcInstance; const n = new TextEncoder().encode(c).length + 1; const q = m._malloc(n); m.stringToUTF8(c, q, n); (window.fcRunPy)(m, q); }, [
      'import FreeCAD as App, json',
      'd = App.newDocument("FF")',
      'b = d.addObject("Part::Box", "B"); b.Length = 10; b.Width = 20; b.Height = 30',
      'd.recompute()',
      'open("/tmp/ff.json", "w").write(json.dumps({"volume": b.Shape.Volume, "verts": len(b.Shape.Vertexes), "version": ".".join(App.Version()[0:3])}))',
    ].join(NL));
    let geom = null;
    for (let i = 0; i < 40; i++) {
      geom = await p.evaluate(() => { try { return window.fcInstance.FS.readFile('/tmp/ff.json', { encoding: 'utf8' }); } catch (e) { return null; } });
      if (geom) break;
      await sl(1500);
    }
    console.log('  geometry: ' + geom);
    let g = {}; try { g = JSON.parse(geom); } catch (e) {}
    ok(g.volume === 6000 && g.verts === 8, 'OCCT computes a correct solid in Firefox: ' + JSON.stringify(g));
    await p.screenshot({ path: 'C:/tmp/firefox-freecad.png' });
    console.log('  screenshot: C:/tmp/firefox-freecad.png');
  }
  if (errors.length) console.log('  page errors: ' + JSON.stringify(errors.slice(0, 5)));
  ok(errors.length === 0, 'no page errors (' + errors.length + ')');

  await b.close();
  console.log(fails ? `${NL}${fails} FAILED` : `${NL}all passed: Firefox runs it`);
  process.exit(fails ? 1 : 0);
})();
