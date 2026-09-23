// Is the browser build's shading the same as desktop FreeCAD's?
//
// Runs scratchpad/lightprobe.py in the browser build, which is the SAME script the desktop
// binary runs, so both sides get one sphere and one box, the same colours, the same
// orthographic camera written out verbatim, and the same image size. Then it compares the
// two renders numerically instead of by eye: the sphere sweeps every normal direction, so a
// wrong light direction or a missing specular term moves its highlight, and the box's three
// faces give three flat samples of the diffuse term at known angles.
//
//   node scratchpad/lightcmp.js [url]            (desktop side: bin/FreeCAD.exe lightprobe.py)
const fs = require('fs');
const zlib = require('zlib');
const puppeteer = require('puppeteer-core');
const sl = (ms) => new Promise((r) => setTimeout(r, ms));
const NL = String.fromCharCode(10);
const URL = process.argv[2] || 'http://127.0.0.1:8792/freecad-gui.html';
const CHROME = process.env.CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const DESKTOP = process.env.DESKTOP_PNG || 'C:/tmp/light-desktop.png';
const OUT = 'C:/tmp/light-wasm.png';
const runPy = (p, c) => p.evaluate((c) => { const m = window.fcInstance; const n = new TextEncoder().encode(c).length + 1; const q = m._malloc(n); m.stringToUTF8(c, q, n); (window.fcRunPy)(m, q); }, c);
const waitFile = async (p, f, ms) => {
  const t = Date.now();
  while (Date.now() - t < ms) {
    const s = await p.evaluate((f) => { try { return window.fcInstance.FS.readFile(f, { encoding: 'utf8' }); } catch (e) { return null; } }, f);
    if (s) return s;
    await sl(1500);
  }
  return null;
};

// PNG reader (8-bit RGB/RGBA, no interlace), same one scratchpad/transcheck.js carries.
function readPNG(file) {
  const buf = fs.readFileSync(file);
  let pos = 8, width = 0, height = 0, colour = 0; const idat = [];
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
const px = (png, x, y) => {
  const i = y * png.stride + x * png.bpp;
  return [png.data[i], png.data[i + 1], png.data[i + 2]];
};
// Where the object is, and how bright: everything above the dark background counts.
function analyse(png) {
  let minX = 1e9, minY = 1e9, maxX = -1, maxY = -1, lit = 0, sum = 0, best = -1, bestAt = null;
  const hist = new Array(16).fill(0);
  for (let y = 0; y < png.height; y++) {
    for (let x = 0; x < png.width; x++) {
      const [r, g, b] = px(png, x, y);
      const l = (r + g + b) / 3;
      if (l < 55) continue;                       // background is ~40
      lit++; sum += l;
      hist[Math.min(15, Math.floor(l / 16))]++;
      if (x < minX) minX = x; if (x > maxX) maxX = x;
      if (y < minY) minY = y; if (y > maxY) maxY = y;
      if (l > best) { best = l; bestAt = [x, y]; }
    }
  }
  return { lit, mean: +(sum / Math.max(1, lit)).toFixed(1), max: Math.round(best),
           highlightAt: bestAt, bbox: [minX, minY, maxX, maxY], hist };
}

(async () => {
  const script = fs.readFileSync('scratchpad/lightprobe.py', 'utf8');
  const b = await puppeteer.launch({ executablePath: CHROME, headless: true, defaultViewport: { width: 1400, height: 900 },
    args: ['--no-sandbox', '--use-gl=angle'], protocolTimeout: 900000, userDataDir: 'C:/Users/MICHAE~1/AppData/Local/Temp/fc-lc-' + Date.now() });
  const p = (await b.pages())[0];
  await p.goto(URL, { waitUntil: 'domcontentloaded', timeout: 300000 });
  const t = Date.now();
  while (Date.now() - t < 420000) { if (await p.evaluate(() => !!window.__fcWorkReady && !!(window.fcInstance && window.fcInstance._malloc))) break; await sl(1500); }
  await sl(9000);

  await p.evaluate((src) => { window.fcInstance.FS.writeFile('/tmp/lightprobe.py', src); }, script);
  // The variant is an environment variable in the probe, and the wasm interpreter has its
  // own environment, so it has to be set inside rather than inherited from the shell.
  const variant = process.env.FCWEB_LIGHT_VARIANT || 'full';
  await runPy(p, ['import os',
                  'os.environ["FCWEB_LIGHT_VARIANT"] = ' + JSON.stringify(variant),
                  'os.environ["FCWEB_LIGHT_LAYOUT"] = ' + JSON.stringify(process.env.FCWEB_LIGHT_LAYOUT || 'default'),
                  'exec(open("/tmp/lightprobe.py").read())'].join(NL));
  console.log('  variant: ' + variant);
  console.log('  probe: ' + (await waitFile(p, '/tmp/lightprobe.json', 120000)));
  await sl(4000);

  // The same call the desktop side used, so both images come off FreeCAD's own renderer.
  await runPy(p, [
    'import FreeCADGui as Gui, json, traceback',
    'o = {}',
    'try:',
    '    v = Gui.activeDocument().activeView()',
    '    v.saveImage("/tmp/light-wasm.png", 900, 700, "Current")',
    '    import os; o["bytes"] = os.path.getsize("/tmp/light-wasm.png")',
    'except Exception:',
    '    o["exc"] = traceback.format_exc()[-400:]',
    'open("/tmp/saveimage.json", "w").write(json.dumps(o))',
  ].join(NL));
  const saved = await waitFile(p, '/tmp/saveimage.json', 120000);
  console.log('  saveImage: ' + saved);

  let got = false;
  if (saved && saved.indexOf('bytes') > 0) {
    const b64 = await p.evaluate(() => {
      const d = window.fcInstance.FS.readFile('/tmp/light-wasm.png');
      let s = ''; for (let i = 0; i < d.length; i += 8192) s += String.fromCharCode.apply(null, d.subarray(i, i + 8192));
      return btoa(s);
    });
    fs.writeFileSync(OUT, Buffer.from(b64, 'base64'));
    got = true;
  }
  await b.close();
  if (!got) { console.log('  the browser build could not save an image; compare from a screenshot instead'); return; }

  const d = analyse(readPNG(DESKTOP)), w = analyse(readPNG(OUT));
  const pad = (s) => String(s).padEnd(22);
  console.log(NL + '  ' + pad('') + 'desktop        browser');
  console.log('  ' + pad('lit pixels') + String(d.lit).padEnd(15) + w.lit);
  console.log('  ' + pad('mean brightness') + String(d.mean).padEnd(15) + w.mean);
  console.log('  ' + pad('peak brightness') + String(d.max).padEnd(15) + w.max);
  console.log('  ' + pad('highlight at') + JSON.stringify(d.highlightAt).padEnd(15) + JSON.stringify(w.highlightAt));
  console.log('  ' + pad('bounding box') + JSON.stringify(d.bbox).padEnd(15) + JSON.stringify(w.bbox));
  console.log(NL + '  brightness histogram (16 buckets, lit pixels only)');
  console.log('  desktop ' + d.hist.map(x => String(x).padStart(6)).join(''));
  console.log('  browser ' + w.hist.map(x => String(x).padStart(6)).join(''));
  // Where the two renders still differ, as a coarse grid over the object's bounding box,
  // so a difference can be attributed to a surface rather than to "the picture".
  const D = readPNG(DESKTOP), W = readPNG(OUT);
  const [x0, y0, x1, y1] = d.bbox;
  const cols = 10, rows = 8;
  let worst = [];
  console.log(NL + '  per-region mean brightness (desktop -> browser, difference)');
  for (let ry = 0; ry < rows; ry++) {
    let line = '  ';
    for (let rx = 0; rx < cols; rx++) {
      const ax = Math.round(x0 + (x1 - x0) * rx / cols), bx = Math.round(x0 + (x1 - x0) * (rx + 1) / cols);
      const ay = Math.round(y0 + (y1 - y0) * ry / rows), by = Math.round(y0 + (y1 - y0) * (ry + 1) / rows);
      let sd = 0, sw = 0, n = 0;
      for (let y = ay; y < by; y++) for (let x = ax; x < bx; x++) {
        const [r1, g1, b1] = px(D, x, y), [r2, g2, b2] = px(W, x, y);
        const l1 = (r1 + g1 + b1) / 3, l2 = (r2 + g2 + b2) / 3;
        if (l1 < 55 && l2 < 55) continue;
        sd += l1; sw += l2; n++;
      }
      if (!n) { line += '    .'; continue; }
      const diff = Math.round(sw / n - sd / n);
      worst.push({ at: [ax, ay], desktop: Math.round(sd / n), browser: Math.round(sw / n), diff });
      line += String(diff > 0 ? '+' + diff : diff).padStart(5);
    }
    console.log(line);
  }
  worst.sort((a, b2) => Math.abs(b2.diff) - Math.abs(a.diff));
  console.log(NL + '  largest regional differences:');
  worst.slice(0, 5).forEach(w2 => console.log('    at ' + JSON.stringify(w2.at) + '  desktop ' + w2.desktop + '  browser ' + w2.browser + '  ' + (w2.diff > 0 ? '+' : '') + w2.diff));
  console.log(NL + '  images: ' + DESKTOP + '  ' + OUT);
})();
