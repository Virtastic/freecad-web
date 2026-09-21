// Browser-wall gate check. Serves play-gui/ on a private port with COOP/COEP and drives
// play-gui/freecad-gui.html through the four cases the gate must get right:
//   1. desktop Chrome            -> no wall, loader present, FreeCAD.js requested
//   2. no JSPI (promising stub)  -> wall, k=jspi, ZERO engine requests
//   3. phone (iPhone emulation)  -> wall (mobile variant), k=mobile, zero engine requests
//   4. phone + ?force=1          -> no wall, FreeCAD.js requested
// Case 2 stubs WebAssembly.promising before any page script runs: the installed Chrome
// ships JSPI unflagged (137+), so no launch flag turns it off; the stub exercises the same
// refusal path a real non-JSPI browser takes. Exit code 1 on any failed assertion.
//   node scratchpad/wall.js
const puppeteer = require('puppeteer-core');
const { spawn } = require('child_process');
const path = require('path');
const CHROME = process.env.CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const PORT = 8797;
const URL0 = `http://127.0.0.1:${PORT}/freecad-gui.html`;
let fails = 0;
const ok = (c, m) => { console.log((c ? '  ok   ' : '  FAIL ') + m); if (!c) fails++; };

async function run(name, { init, mobile, url }) {
  const b = await puppeteer.launch({ executablePath: CHROME, headless: true, args: ['--no-sandbox'] });
  const p = await b.newPage();
  if (mobile) await p.emulate(puppeteer.KnownDevices['iPhone 13']);
  if (init) await p.evaluateOnNewDocument(init);
  const engine = [], beacons = [];
  p.on('request', r => {
    const u = r.url();
    if (/FreeCAD\.|qtloader/.test(u)) engine.push(u);
    if (/\/t\?/.test(u)) beacons.push(u);
    if (/FreeCAD\.(wasm|data)/.test(u)) r.abort(); else r.continue();
  });
  await p.setRequestInterception(true);
  await p.goto(url || URL0, { waitUntil: 'domcontentloaded' });
  await new Promise(r => setTimeout(r, 2500));
  const st = await p.evaluate(() => ({
    wall: !!document.querySelector('#wall.show'),
    load: !!document.getElementById('load'),
    title: (document.getElementById('w-title') || {}).textContent || '',
    seen: (document.getElementById('w-seen') || {}).textContent || '',
    mobileBtns: !!(document.getElementById('w-btns-mobile') && !document.getElementById('w-btns-mobile').hidden),
    walled: document.body.className.indexOf('walled') >= 0,
  }));
  await b.close();
  console.log(name);
  return { st, engine, beacons };
}

(async () => {
  const srv = spawn(process.execPath, [path.join(__dirname, 'testserver.js'), path.join(__dirname, '..', 'play-gui'), String(PORT)], { stdio: 'ignore' });
  await new Promise(r => setTimeout(r, 800));
  try {
    let r = await run('1. desktop Chrome', {});
    ok(!r.st.wall, 'no wall'); ok(r.st.load, 'loader present');
    ok(r.engine.some(u => /FreeCAD\.js/.test(u)), 'FreeCAD.js requested');
    ok(!r.beacons.some(u => /boot_gate/.test(u)), 'no boot_gate beacon');

    r = await run('2. no JSPI', { init: () => { delete WebAssembly.promising; } });
    ok(r.st.wall, 'wall shown'); ok(!r.st.load, 'loader removed'); ok(r.st.walled, 'body.walled');
    ok(/Chrome or Edge on a desktop/.test(r.st.title), 'desktop headline: ' + r.st.title);
    ok(/You are on (Google )?Chrome \d+ on Windows/.test(r.st.seen), 'seen line: ' + r.st.seen);
    ok(r.engine.length === 0, 'zero engine requests (' + r.engine.length + ')');
    ok(r.beacons.some(u => /e=boot_gate&.*k=jspi/.test(u)), 'beacon k=jspi');

    r = await run('3. phone', { mobile: true });
    ok(r.st.wall, 'wall shown'); ok(r.st.mobileBtns, 'mobile buttons');
    ok(/desktop or laptop/.test(r.st.title), 'mobile headline: ' + r.st.title);
    ok(r.engine.length === 0, 'zero engine requests');
    ok(r.beacons.some(u => /e=boot_gate&.*k=mobile/.test(u)), 'beacon k=mobile');

    r = await run('4. phone + ?force=1', { mobile: true, url: URL0 + '?force=1' });
    ok(!r.st.wall, 'no wall'); ok(r.engine.some(u => /FreeCAD\.js/.test(u)), 'FreeCAD.js requested');
  } finally { srv.kill(); }
  console.log(fails ? `\n${fails} FAILED` : '\nall passed');
  process.exit(fails ? 1 : 0);
})();
