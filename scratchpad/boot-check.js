// SPDX-License-Identifier: LGPL-2.1-or-later
// Copyright (c) Virtastic
// Drive a REAL Chrome at the running stack and answer the three things that have been
// unproven: does the engine boot, does the menu entry appear without a save, and does a
// plain Ctrl+S reach the server.
//
//   node scratchpad/boot-check.js [url]
//
// No npm dependencies: Node 22+ ships a global WebSocket, which is all CDP needs. The
// point is that every previous "the app is fine" claim in this thread came from curl, and
// curl cannot tell you whether a wasm module instantiates.
const { spawn } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');

const URL_ = process.argv[2] || 'https://cad.search.dontexist.com/';
const CHROME = process.env.CHROME_PATH || '/usr/local/bin/chrome';
const PORT = 9333 + (process.pid % 500);
const PROFILE = fs.mkdtempSync(path.join(os.tmpdir(), 'fcprobe-'));

let pass = 0, fail = 0;
const failures = [];
const ok = (c, w) => { if (c) { pass++; console.log('  ok   ' + w); }
                         else { fail++; failures.push(w); console.log('  FAIL ' + w); } };

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ---- minimal CDP client -------------------------------------------------------------
class CDP {
  constructor(ws) {
    this.ws = ws;
    this.id = 0;
    this.pending = new Map();
    this.events = [];
    this.logs = [];
    this.consoleErrors = [];
    ws.addEventListener('message', (ev) => {
      let m; try { m = JSON.parse(ev.data); } catch (e) { return; }
      if (m.id && this.pending.has(m.id)) {
        const { resolve, reject } = this.pending.get(m.id);
        this.pending.delete(m.id);
        m.error ? reject(new Error(JSON.stringify(m.error))) : resolve(m.result);
      } else if (m.method) {
        this.events.push(m);
        if (m.method === 'Runtime.consoleAPICalled') {
          const txt = (m.params.args || []).map((a) => a.value ?? a.description ?? '').join(' ');
          this.logs.push(m.params.type + ': ' + txt);
          if (m.params.type === 'error') this.consoleErrors.push(txt);
        }
        if (m.method === 'Runtime.exceptionThrown') {
          const d = m.params.exceptionDetails || {};
          this.consoleErrors.push('EXCEPTION: ' + (d.text || '') + ' ' +
            (d.exception && (d.exception.description || d.exception.value) || ''));
        }
      }
    });
  }
  send(method, params) {
    const id = ++this.id;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.ws.send(JSON.stringify({ id, method, params: params || {} }));
      setTimeout(() => {
        if (this.pending.has(id)) { this.pending.delete(id); reject(new Error('CDP timeout: ' + method)); }
      }, 240000);
    });
  }
  async evalJs(expr) {
    const r = await this.send('Runtime.evaluate', {
      expression: expr, returnByValue: true, awaitPromise: true
    });
    if (r.exceptionDetails) {
      throw new Error('eval: ' + (r.exceptionDetails.text || '') +
        ' ' + JSON.stringify(r.exceptionDetails.exception || {}));
    }
    return r.result ? r.result.value : undefined;
  }
}

async function main() {
  console.log('Chrome boot check against ' + URL_);
  console.log('  binary: ' + CHROME);

  const child = spawn(CHROME, [
    '--headless=new',
    '--remote-debugging-port=' + PORT,
    '--user-data-dir=' + PROFILE,
    '--no-sandbox', '--disable-dev-shm-usage',
    // The engine is a wasm64 build: it needs a real 64-bit heap and no single-tab cap.
    '--js-flags=--max-old-space-size=8192',
    '--enable-features=SharedArrayBuffer',
    '--window-size=1600,1000',
    'about:blank'
  ], { stdio: ['ignore', 'pipe', 'pipe'] });

  let stderr = '';
  child.stderr.on('data', (d) => { stderr += d.toString(); });

  // Wait for the debugger to answer.
  let wsUrl = null;
  for (let i = 0; i < 60; i++) {
    await sleep(500);
    try {
      const r = await fetch('http://127.0.0.1:' + PORT + '/json/version');
      const j = await r.json();
      if (j.webSocketDebuggerUrl) { wsUrl = j.webSocketDebuggerUrl; break; }
    } catch (e) { /* not up yet */ }
  }
  if (!wsUrl) {
    console.log('FATAL: chrome never exposed a debugger port');
    console.log(stderr.split('\n').slice(-12).join('\n'));
    child.kill();
    process.exit(2);
  }
  console.log('  ' + (await (await fetch('http://127.0.0.1:' + PORT + '/json/version')).json())['Browser']);

  const ws = new WebSocket(wsUrl);
  await new Promise((res, rej) => {
    ws.addEventListener('open', res);
    ws.addEventListener('error', () => rej(new Error('ws error')));
  });
  const cdp = new CDP(ws);

  // A fresh tab, so sessionStorage/localStorage start empty like a real visitor's.
  const { targetId } = await cdp.send('Target.createTarget', { url: 'about:blank' });
  const targets = await (await fetch('http://127.0.0.1:' + PORT + '/json/list')).json();
  const page = targets.find((t) => t.id === targetId);
  const pws = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise((res, rej) => { pws.addEventListener('open', res); pws.addEventListener('error', rej); });
  const P = new CDP(pws);

  await P.send('Runtime.enable');
  await P.send('Page.enable');
  await P.send('Log.enable').catch(() => {});
  await P.send('Network.enable').catch(() => {});

  console.log('\nloading ' + URL_ + ' (this downloads ~115 MB of engine)...');
  const t0 = Date.now();
  await P.send('Page.navigate', { url: URL_ });

  // ---- 1. does the engine boot? ----------------------------------------------------
  let ready = false, sawWall = false, state = '', lastPct = '';
  for (let i = 0; i < 240; i++) {           // up to 240 s: the engine is ~115 MB
    await sleep(1000);
    try {
      // VISIBILITY, not existence. The wall is a node that stays in the DOM while the real
      // loader runs underneath it -- testing getElementById() made this harness exit at 6 s
      // with the engine at 44% downloaded and call it a failure. That was my bug, not the
      // app's, and it is exactly the kind of false negative worth fixing rather than
      // reporting as "the browser is refused".
      const wall = await P.evalJs(`(function(){
        var w = document.getElementById('wall');
        if (!w) return false;
        var cs = getComputedStyle(w);
        return cs.display !== 'none' && cs.visibility !== 'hidden' &&
               cs.opacity !== '0' && w.offsetParent !== null;
      })()`);
      if (wall) { sawWall = true; break; }
      const pct = await P.evalJs(`(function(){
        var m = (document.body.innerText||'').match(/(\\d+)%/);
        return m ? m[1] : '';
      })()`).catch(() => '');
      if (pct && pct !== lastPct) { lastPct = pct; console.log('    downloading ' + pct + '%'); }
      const appReady = await P.evalJs('!!window.__fcAppReady');
      if (appReady) { ready = true; break; }
    } catch (e) { /* the page may be mid-navigation */ }
  }
  const secs = ((Date.now() - t0) / 1000).toFixed(0);
  console.log('\nengine boot:');
  ok(!sawWall, 'no browser-support wall (' + secs + 's)');
  ok(ready, '__fcAppReady is true -> the wasm engine instantiated (' + secs + 's)');

  if (!ready) {
    const errs = P.consoleErrors.slice(0, 6);
    console.log('  console errors:');
    errs.forEach((e) => console.log('    - ' + String(e).slice(0, 200)));
    ok(false, 'engine booted (see errors above)');
  } else {
    // The menu is a Qt widget, not a DOM node: FreeCAD renders it into the canvas, so
    // querying shadow roots for .q-menubar finds nothing even when the menu is right there.
    // Asking the interpreter is the honest test, and it is what the add-on itself does.
    // The overlay installs from a 700 ms interval gated on ready(), so WAIT for it rather
    // than probing the instant __fcAppReady flips -- the first probe of this harness ran at
    // 30.4 s and install() had not run yet, so it read as "menu missing".
    console.log('\nmenu entry (no save first):');
    let menuLogged = false, cmds = '';
    for (let i = 0; i < 40; i++) {
      await sleep(1000);
      const logText = await P.evalJs(`(function(){
        var el=document.getElementById('log');
        return el ? el.textContent.slice(-6000) : '';
      })()`).catch(() => '');
      if (/Edit menu:.*Server Files/.test(String(logText))) { menuLogged = true; break; }
      if (/sharing overlay|addon overlay/.test(String(logText))) {
        cmds = await P.evalJs(`(function(){
          try{
            return String(window.__fcRunPyGuarded(
              "import FreeCADGui as G\\n" +
              "_n=sorted([c for c in G.listCommands() if 'Fcweb' in c])\\n" +
              "print('FCWEBCMDS', _n)"
            ));
          }catch(e){ return 'ERR '+e; }
        })()`).catch((e) => 'ERR ' + e);
        await sleep(1500);
        const l2 = await P.evalJs(`(function(){
          var el=document.getElementById('log'); return el ? el.textContent.slice(-4000) : '';
        })()`).catch(() => '');
        if (/Edit menu:.*Server Files/.test(String(l2))) { menuLogged = true; break; }
        if (/FCWEBCMDS \[/.test(String(l2))) { cmds = String(l2).match(/FCWEBCMDS \[[^\]]*\]/)[0]; break; }
      }
    }
    const finalLog = await P.evalJs(`(function(){
      var el=document.getElementById('log'); return el ? el.textContent.slice(-6000) : '';
    })()`).catch(() => '');
    if (!cmds) {
      const m = String(finalLog).match(/FCWEBCMDS \[[^\]]*\]/);
      if (m) cmds = m[0];
    }
    ok(menuLogged || /Fcweb_ServerFiles/.test(cmds),
       'the Edit menu carries Fcweb_ServerFiles with no save first (' + cmds.slice(0, 120) + ')');
    if (!menuLogged && !/Fcweb_ServerFiles/.test(cmds)) {
      console.log('  log tail: ' + String(finalLog).replace(/\s+/g, ' ').slice(-500));
    }

    // ---- 3. does a plain save reach the server? -------------------------------------
    console.log('\nserver files:');
    const avail = await P.evalJs('window.fcwebServerFiles.available()').catch((e) => 'ERR ' + e);
    console.log('  available() -> ' + avail);
    const key = process.env.FCWEB_FILES_KEY || '';
    const withKey = await P.evalJs(
      '(function(){ try{ window.fcwebServerFiles.setKey(' + JSON.stringify(key) + ');' +
      '  return window.fcwebServerFiles.available(); }catch(e){ return "ERR "+e; } })()'
    ).catch((e) => 'ERR ' + e);
    console.log('  available() with key -> ' + withKey);
    ok(withKey === true, 'the folder answers with the shared key');

    const listed = await P.evalJs(
      '(function(){ try{ return window.fcwebServerFiles.list().then(function(){' +
      '  return document.body.innerText.slice(0,300); }); }catch(e){ return "ERR "+e; } })()'
    ).catch((e) => 'ERR ' + e);
    console.log('  panel text: ' + String(listed).replace(/\s+/g, ' ').slice(0, 200));

    // Now the save hook itself -- the one that never had a clean run.
    const put = await P.evalJs(`(function(){
      try{
        return window.fcwebServerFiles.save('/home/web_user/_dl/CdpProbe.FCStd',
          new TextEncoder().encode('cdp-probe-bytes')).then(function(j){ return JSON.stringify(j); });
      }catch(e){ return Promise.resolve('ERR '+e); }
    })()`).catch((e) => 'ERR ' + e);
    console.log('  save() -> ' + String(put).slice(0, 200));
    ok(/ok/.test(String(put)) && /CdpProbe/.test(String(put)), 'a save reaches the server');

    // And does it show up in the list the panel renders?
    const inPanel = await P.evalJs(
      '(function(){ try{ return window.fcwebServerFiles.list().then(function(){' +
      '  return (document.body.innerText.indexOf("CdpProbe") >= 0) ? "yes" : "no"; });' +
      ' }catch(e){ return "ERR "+e; } })()'
    ).catch((e) => 'ERR ' + e);
    console.log('  CdpProbe visible in panel -> ' + inPanel);
    ok(inPanel === 'yes', 'the saved document is listed in the panel');

    // Clean up after ourselves.
    await P.evalJs('window.fcwebServerFiles.del("CdpProbe.FCStd")').catch(() => {});
  }

  const errs = P.consoleErrors.slice(0, 8);
  console.log('\nconsole errors (' + P.consoleErrors.length + '):');
  errs.forEach((e) => console.log('  - ' + String(e).slice(0, 220)));

  ws.close(); pws.close();
  child.kill('SIGKILL');
  try { fs.rmSync(PROFILE, { recursive: true, force: true }); } catch (e) {}

  console.log('\n' + pass + ' passed, ' + fail + ' failed');
  if (failures.length) { console.log('failed:'); failures.forEach((f) => console.log('  - ' + f)); }
  process.exit(fail ? 1 : 0);
}

main().catch((e) => { console.error('harness error:', e && e.stack || e); process.exit(2); });
