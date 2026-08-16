// Why does datasafety's port not boot? Report what the page is actually doing.
const puppeteer = require('puppeteer-core');
const CHROME = process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';  // set CHROME_PATH to run off macOS
const sl = (ms) => new Promise((r) => setTimeout(r, ms));
(async () => {
  const url = process.argv[2];
  const b = await puppeteer.launch({ executablePath: CHROME, headless: false, defaultViewport: null,
    args: ['--no-sandbox','--use-gl=angle','--use-angle=metal','--window-size=1300,850'],
    protocolTimeout: 600000, userDataDir: '/tmp/fc-bootprobe' });
  const p = (await b.pages())[0];
  const errs = []; p.on('pageerror', (e) => errs.push(String(e).split('\n')[0].slice(0,160)));
  const failed = []; p.on('requestfailed', (r) => failed.push(r.url().slice(-40) + ' ' + (r.failure() || {}).errorText));
  await p.goto(url, { waitUntil: 'domcontentloaded', timeout: 300000 });
  for (let i = 0; i < 10; i++) {
    await sl(30000);
    const st = await p.evaluate(() => ({
      inst: !!(window.fcInstance && window.fcInstance._malloc),
      log: (document.getElementById('log') ? document.getElementById('log').textContent : '(no log element)').slice(-260),
    }));
    console.log(`t=${(i+1)*30}s instance=${st.inst}`);
    if (st.inst) { console.log('BOOTED'); break; }
    if (i === 2 || i === 9) console.log('  log tail: ' + JSON.stringify(st.log));
  }
  console.log('page errors: ' + (errs.length ? errs.slice(0,3).join(' | ') : 'none'));
  console.log('failed requests: ' + (failed.length ? failed.slice(0,5).join(' | ') : 'none'));
  await b.close().catch(()=>{}); process.exit(0);
})().catch((e)=>{console.log('DRIVER '+String(e).slice(0,200));process.exit(0);});
