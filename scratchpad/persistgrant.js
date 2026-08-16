// Does a genuinely-engaged user get persistent storage? Chrome grants persist() without a
// prompt based on site engagement (interaction time, repeat visits), bookmarks, or
// installation. A fresh scripted profile has none of that, which is why it reads false.
// Same profile, several visits, real interaction each time, checking after each.
const puppeteer = require('puppeteer-core');
const CHROME = process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';  // set CHROME_PATH to run off macOS
const sl = (ms) => new Promise((r) => setTimeout(r, ms));
const PROFILE = '/tmp/fc-persist-' + (process.argv[3] || 'a');
const URL = process.argv[2] || 'https://freecad.virtastic.app/';

async function visit(n) {
  const b = await puppeteer.launch({ executablePath: CHROME, headless: false, defaultViewport: null,
    args: ['--no-sandbox', '--use-gl=angle', '--use-angle=metal', '--window-size=1300,850'],
    protocolTimeout: 1200000, userDataDir: PROFILE });
  const p = (await b.pages())[0];
  await p.goto(URL, { waitUntil: 'domcontentloaded', timeout: 300000 });
  const t0 = Date.now();
  while (Date.now() - t0 < 300000) { if (await p.evaluate(() => !!(window.fcInstance && window.fcInstance._malloc))) break; await sl(1000); }
  await sl(12000);
  // real interaction: Chrome's site-engagement score rises with clicks and dwell time
  for (let i = 0; i < 14; i++) {
    await p.mouse.click(600 + (i % 5) * 40, 400 + (i % 3) * 30);
    await p.keyboard.press('Shift');
    await sl(900);
  }
  await sl(6000);
  const st = await p.evaluate(async () => {
    const before = await navigator.storage.persisted();
    const asked = await navigator.storage.persist();
    const after = await navigator.storage.persisted();
    const q = await navigator.storage.estimate();
    return { before, asked, after, usageMB: Math.round(q.usage / 1048576), quotaMB: Math.round(q.quota / 1048576) };
  });
  console.log('visit ' + n + ': persisted before=' + st.before + ' persist()=' + st.asked +
    ' after=' + st.after + '  storage ' + st.usageMB + '/' + st.quotaMB + ' MB');
  await b.close().catch(() => {});
  return st.after;
}
(async () => {
  for (let n = 1; n <= 3; n++) {
    const got = await visit(n);
    if (got) { console.log('=> granted on visit ' + n); process.exit(0); }
    await sl(3000);
  }
  console.log('=> still not granted after 3 engaged visits');
  process.exit(0);
})().catch((e) => { console.log('DRIVER ' + String(e).slice(0, 200)); process.exit(0); });
