// Where does the fast-reload case actually lose the work: the Python save, the FS write,
// or the IndexedDB flush? Sample all three at 1 s intervals after an edit.
const puppeteer = require('puppeteer-core');
const fs = require('fs');
const CHROME = process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';  // set CHROME_PATH to run off macOS
const sl = (ms) => new Promise((r) => setTimeout(r, ms));
const run = (p, c) => p.evaluate((c) => { const m = window.fcInstance;
  const n = new TextEncoder().encode(c).length + 1; const q = m._malloc(n); m.stringToUTF8(c, q, n);
  (window.fcRunPy || ((mm, pp) => { mm._fcweb_run_python(pp); mm._free(pp); }))(m, q); }, c);
(async () => {
  const b = await puppeteer.launch({ executablePath: CHROME, headless: false, defaultViewport: null,
    args: ['--no-sandbox', '--use-gl=angle', '--use-angle=metal', '--window-size=1200,800'],
    protocolTimeout: 1200000, userDataDir: '/tmp/fc-saveprobe-' + Date.now() });
  const p = (await b.pages())[0];
  await p.goto('http://localhost:8791/index.html', { waitUntil: 'domcontentloaded', timeout: 300000 });
  const t0 = Date.now();
  while (Date.now() - t0 < 300000) { if (await p.evaluate(() => !!(window.fcInstance && window.fcInstance._malloc))) break; await sl(1000); }
  await sl(17000);
  await run(p, fs.readFileSync('/tmp/saveprobe.py', 'utf8'));
  await sl(1200);
  const log0 = await p.evaluate(() => document.getElementById('log').textContent);
  console.log((log0.match(/SP [^\n]*/g) || []).join('\n'));
  const tEdit = Date.now();
  for (let i = 0; i < 8; i++) {
    const st = await p.evaluate(() => {
      const m = window.fcInstance;
      let onFs = false, sz = 0;
      try { const s = m.FS.stat('/home/web_user/.FreeCAD/recovery/ProbeDoc.FCStd'); onFs = true; sz = s.size; } catch (e) {}
      return { onFs, sz, hasSync: typeof m.fcwebSyncFS };
    });
    // is it in IndexedDB yet?
    const inIdb = await p.evaluate(() => new Promise((res) => {
      let req; try { req = indexedDB.open('/home/web_user'); } catch (e) { return res('err'); }
      req.onerror = () => res('err');
      req.onsuccess = () => { const db = req.result;
        if (!db.objectStoreNames.contains('FILE_DATA')) { db.close(); return res('nostore'); }
        const tx = db.transaction('FILE_DATA', 'readonly');
        const g = tx.objectStore('FILE_DATA').getAllKeys();
        g.onsuccess = () => { const k = g.result.filter((x) => String(x).includes('ProbeDoc'));
          db.close(); res(k.length ? 'YES(' + k.length + ')' : 'no'); };
        g.onerror = () => { db.close(); res('err'); }; };
    }));
    console.log('  t=+' + ((Date.now() - tEdit) / 1000).toFixed(1) + 's  recoveryFile=' + st.onFs +
      ' size=' + st.sz + '  inIndexedDB=' + inIdb + '  syncFn=' + st.hasSync);
    await sl(1000);
  }
  await b.close().catch(() => {}); process.exit(0);
})().catch((e) => { console.log('DRIVER ' + String(e).slice(0, 200)); process.exit(0); });
