// Capture the full boot abort message + console for the 291MB build.
const puppeteer = require('puppeteer-core');
const CHROME = process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';  // set CHROME_PATH to run off macOS
const ARGS = ['--no-sandbox','--disable-dev-shm-usage','--disable-gpu-sandbox',
  '--js-flags=--max-old-space-size=8192','--use-gl=angle','--use-angle=swiftshader',
  '--enable-features=SharedArrayBuffer','--ignore-gpu-blocklist'];
(async () => {
  const b = await puppeteer.launch({ executablePath: CHROME, headless: 'new', args: ARGS,
    protocolTimeout: 300000, userDataDir: '/tmp/fc-chrome-profile' });
  const page = await b.newPage();
  const con = [];
  page.on('console', m => con.push('[con] ' + m.text()));
  page.on('pageerror', e => con.push('[PAGEERROR] ' + e.message));
  await page.goto('http://localhost:8799/freecad-gui.html', { waitUntil: 'domcontentloaded', timeout: 60000 });
  await new Promise(r => setTimeout(r, 130000));
  let log = '';
  try { log = await page.evaluate(() => { const e = document.getElementById('log'); return e ? e.innerText : '(no log el)'; }); } catch(e){ log='[eval-threw]'; }
  console.log('=== FULL ON-PAGE LOG ===');
  console.log(log);
  console.log('=== CONSOLE (all) ===');
  console.log(con.join('\n'));
  await b.close().catch(()=>{});
})().catch(e => { console.error('ERR', e.message); process.exit(1); });
