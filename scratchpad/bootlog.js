const puppeteer = require('puppeteer-core');
const CHROME = process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';  // set CHROME_PATH to run off macOS
(async () => {
  const b = await puppeteer.launch({ executablePath: CHROME, headless: 'new',
    args: ['--no-sandbox','--disable-dev-shm-usage','--disable-gpu-sandbox','--js-flags=--max-old-space-size=8192','--use-gl=angle','--use-angle=swiftshader','--enable-features=SharedArrayBuffer','--ignore-gpu-blocklist'] });
  const page = await b.newPage();
  const con=[]; page.on('console',m=>con.push(m.text())); page.on('pageerror',e=>con.push('[PAGEERROR] '+e.message));
  await page.goto('http://localhost:8791/freecad-gui.html',{waitUntil:'domcontentloaded',timeout:60000});
  await new Promise(r=>setTimeout(r,55000));
  const log = await page.evaluate(()=>document.getElementById('log').innerText);
  console.log('=== LOG TAIL ===\n'+log.split('\n').slice(-25).join('\n'));
  console.log('=== CONSOLE ERR/ABORT ===\n'+con.filter(l=>/error|abort|Error|exception|RuntimeError|assert|PAGEERROR|Traceback/i.test(l)).slice(-25).join('\n'));
  await b.close();
})().catch(e=>{console.error('ERR',e);process.exit(1);});
