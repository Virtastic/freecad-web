// Rasterise FreeCAD's own SVG into the PNG sizes a web app manifest needs. No rsvg or
// inkscape here, and PIL cannot read SVG -- but a browser can, and one is already a
// dependency of the test suite.
const puppeteer = require('puppeteer-core');
const fs = require('fs');
const CHROME = process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';  // set CHROME_PATH to run off macOS
const SVG = fs.readFileSync(process.argv[2], 'utf8');
(async () => {
  const b = await puppeteer.launch({ executablePath: CHROME, headless: 'new', args: ['--no-sandbox'] });
  const p = await b.newPage();
  for (const size of [192, 512]) {
    await p.setViewport({ width: size, height: size, deviceScaleFactor: 1 });
    // maskable icons want the artwork inset ~10% so a circular mask cannot clip it
    await p.setContent('<html><body style="margin:0;background:#2b2f36;display:flex;' +
      'align-items:center;justify-content:center;width:' + size + 'px;height:' + size + 'px">' +
      '<div style="width:80%;height:80%;display:flex;align-items:center;justify-content:center">' +
      SVG + '</div></body></html>');
    await p.evaluate((s) => { const el = document.querySelector('svg');
      if (el) { el.setAttribute('width', s * 0.8); el.setAttribute('height', s * 0.8); } }, size);
    await new Promise((r) => setTimeout(r, 400));
    await p.screenshot({ path: 'play-gui/icon-' + size + '.png', omitBackground: false });
    console.log('wrote play-gui/icon-' + size + '.png');
  }
  await b.close(); process.exit(0);
})().catch((e) => { console.log('ERR ' + e); process.exit(1); });
