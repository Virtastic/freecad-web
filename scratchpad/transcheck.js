// Does a transparent object actually let what is behind it through?
//
// The regression guard for the bug reported 2026-09-22: every transparent object rendered
// opaque, because SoBrepFaceSet::GLRender skipped shouldGLRender() under __EMSCRIPTEN__
// and that call is what hands the shape to SoGLRenderAction::handleTransparency(), which
// delays it into the sorted blending pass.
//
// The scene is a red box with a 70% transparent green plate in front of it, so a correct
// render shows red THROUGH the green. Judged from the screenshot rather than the canvas:
// the WebGL context has no preserveDrawingBuffer, so reading it back from the page returns
// an undrawn frame (this project has been caught by that before).
//
//   node scratchpad/transcheck.js [url]
const fs = require('fs');
const zlib = require('zlib');
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

// Minimal PNG reader: enough for what Chrome writes (8-bit RGB/RGBA, no interlace).
function readPNG(file) {
  const buf = fs.readFileSync(file);
  let pos = 8, width = 0, height = 0, colour = 0, idat = [];
  while (pos < buf.length) {
    const len = buf.readUInt32BE(pos), type = buf.toString('ascii', pos + 4, pos + 8);
    const data = buf.slice(pos + 8, pos + 8 + len);
    if (type === 'IHDR') { width = data.readUInt32BE(0); height = data.readUInt32BE(4); colour = data[9]; }
    else if (type === 'IDAT') idat.push(data);
    else if (type === 'IEND') break;
    pos += len + 12;
  }
  const bpp = colour === 6 ? 4 : 3;
  const raw = zlib.inflateSync(Buffer.concat(idat));
  const stride = width * bpp;
  const out = Buffer.alloc(height * stride);
  let o = 0;
  for (let y = 0; y < height; y++) {
    const filter = raw[o++];
    const line = raw.slice(o, o + stride); o += stride;
    const prev = y ? out.slice((y - 1) * stride, y * stride) : Buffer.alloc(stride);
    const cur = out.slice(y * stride, (y + 1) * stride);
    for (let x = 0; x < stride; x++) {
      const a = x >= bpp ? cur[x - bpp] : 0, b = prev[x], c = x >= bpp ? prev[x - bpp] : 0, v = line[x];
      let val;
      if (filter === 0) val = v;
      else if (filter === 1) val = v + a;
      else if (filter === 2) val = v + b;
      else if (filter === 3) val = v + ((a + b) >> 1);
      else { const pa = Math.abs(b - c), pb = Math.abs(a - c), pc = Math.abs(a + b - 2 * c);
             val = v + (pa <= pb && pa <= pc ? a : (pb <= pc ? b : c)); }
      cur[x] = val & 255;
    }
  }
  return { width, height, bpp, stride, data: out };
}
// Average colour of a rectangle, as {r, g, b}.
function patch(png, x, y, w, h) {
  let R = 0, G = 0, B = 0, n = 0;
  for (let yy = y; yy < y + h; yy++) {
    for (let xx = x; xx < x + w; xx++) {
      const i = yy * png.stride + xx * png.bpp;
      R += png.data[i]; G += png.data[i + 1]; B += png.data[i + 2]; n++;
    }
  }
  return { r: Math.round(R / n), g: Math.round(G / n), b: Math.round(B / n) };
}

const SCENE = [
  'import FreeCAD as App, FreeCADGui as Gui, json',
  'd = App.newDocument("TR")',
  'back = d.addObject("Part::Box", "Back"); back.Length = 40; back.Width = 40; back.Height = 40',
  'front = d.addObject("Part::Box", "Front"); front.Length = 60; front.Width = 5; front.Height = 60',
  'front.Placement.Base = App.Vector(-10, -20, -10)',
  'd.recompute()',
  'back.ViewObject.ShapeColor = (0.9, 0.1, 0.1)',
  'front.ViewObject.ShapeColor = (0.1, 0.9, 0.1)',
  'front.ViewObject.Transparency = 70',
  'v = Gui.activeDocument().activeView()',
  'v.viewAxonometric(); Gui.SendMsgToActiveView("ViewFit"); Gui.updateGui()',
  'open("/tmp/tr.json", "w").write(json.dumps({"transparency": front.ViewObject.Transparency}))',
].join(NL);

(async () => {
  const b = await puppeteer.launch({ executablePath: CHROME, headless: true, defaultViewport: { width: 1400, height: 900 },
    args: ['--no-sandbox', '--use-gl=angle'], protocolTimeout: 900000, userDataDir: 'C:/Users/MICHAE~1/AppData/Local/Temp/fc-tr-' + Date.now() });
  const p = (await b.pages())[0];
  await p.goto(URL, { waitUntil: 'domcontentloaded', timeout: 300000 });
  const t = Date.now();
  while (Date.now() - t < 420000) { if (await p.evaluate(() => !!window.__fcWorkReady && !!(window.fcInstance && window.fcInstance._malloc))) break; await sl(1500); }
  await sl(9000);
  await runPy(p, SCENE);
  console.log('  scene: ' + await waitFile(p, '/tmp/tr.json', 90000));
  await sl(9000);
  const shot = 'C:/tmp/transcheck.png';
  await p.screenshot({ path: shot });
  const png = readPNG(shot);

  // Three samples: the green plate where it covers the red box, the green plate over
  // empty background, and the bare red box.
  // Screenshots come back at the device pixel ratio, so the sample boxes are written in
  // CSS pixels and scaled. Getting this wrong samples the tree view and reads as "opaque".
  const k = png.width / 1400;
  const box = (x, y, w, h) => patch(png, Math.round(x * k), Math.round(y * k), Math.round(w * k), Math.round(h * k));
  // Positions for FreeCAD's layout WITH its status bar, as desktop has it (the web build hid
  // the status bar until 2026-09-23, which made the 3D view 34 px taller).
  const overlap = box(720, 420, 60, 60);   // plate where it covers the red box
  const alone = box(570, 420, 60, 60);     // plate over empty background
  const red = box(920, 560, 60, 60);       // the red box beside the plate
  console.log('  screenshot ' + png.width + 'x' + png.height + ' (scale ' + k + ')');
  console.log('  green over red: ' + JSON.stringify(overlap));
  console.log('  green over background: ' + JSON.stringify(alone));
  console.log('  red box: ' + JSON.stringify(red));

  // Opaque green shows the same colour in both places. Blended green picks up the red
  // behind it, so its red channel rises well above the green-over-background sample.
  const lift = overlap.r - alone.r;
  console.log('  red picked up through the plate: ' + lift);
  ok(red.r > 90 && red.g < 90, 'the red box renders red: ' + JSON.stringify(red));
  // Hue, not brightness: shading changed when glColor stopped driving the ambient material
  // to match desktop (lightcmp.js), and an absolute threshold would fail on a correct render.
  ok(alone.g > 60 && alone.g > alone.r * 1.8 && alone.g > alone.b * 1.8,
     'the green plate renders green: ' + JSON.stringify(alone));
  ok(lift > 25, 'the red box shows THROUGH the 70% transparent plate (red lift ' + lift + ', needs > 25)');
  console.log('  screenshot: ' + shot);
  await b.close();
  console.log(fails ? `${NL}${fails} FAILED` : `${NL}all passed: transparency works`);
  process.exit(fails ? 1 : 0);
})();
