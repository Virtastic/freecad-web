// Headless-Chrome driver for the FreeCAD-wasm browser build.
// Boots the page (optionally with ?render3d=1&autotest=1), waits, then dumps
// the page log + console and screenshots. Reusable smoke/regression harness.
//   node scratchpad/drive.js "render3d=1&autotest=1" /tmp/fc-smoke.png 45
const puppeteer = require('puppeteer-core');
const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';

(async () => {
  const query = process.argv[2] || 'render3d=1&autotest=1';
  const shot  = process.argv[3] || '/tmp/fc-smoke.png';
  const waitS = parseInt(process.argv[4] || '45', 10);
  const url = `http://localhost:8791/freecad-gui.html?${query}`;

  const browser = await puppeteer.launch({
    executablePath: CHROME, headless: 'new',
    args: ['--no-sandbox','--disable-dev-shm-usage','--disable-gpu-sandbox','--js-flags=--max-old-space-size=8192','--use-gl=angle','--use-angle=swiftshader',
           '--enable-features=SharedArrayBuffer','--ignore-gpu-blocklist',
           '--window-size=1400,900'],
  });
  const page = await browser.newPage();
  await page.setViewport({ width: 1400, height: 900 });
  const console_lines = [];
  page.on('console', m => console_lines.push('[console] ' + m.text()));
  page.on('pageerror', e => console_lines.push('[PAGEERROR] ' + e.message));

  console.log('loading', url);
  await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 60000 });
  await new Promise(r => setTimeout(r, waitS * 1000));

  const log = await page.evaluate(() => {
    const el = document.getElementById('log');
    return el ? el.innerText : '(no log el)';
  });
  const diag = await page.evaluate(() => ({
    mvp: window.__mvp || null, ovOpaque: window.__ovOpaque, ovErr: window.__ovErr,
    gllog: (window.__gllog||[]).length,
  }));

  await page.screenshot({ path: shot });
  console.log('=== PAGE LOG ===\n' + log);
  console.log('=== CONSOLE (last 60) ===\n' + console_lines.slice(-60).join('\n'));
  console.log('=== DIAG ===\n' + JSON.stringify(diag, null, 2));
  console.log('screenshot ->', shot);
  await browser.close();
})().catch(e => { console.error('DRIVE ERROR', e); process.exit(1); });
