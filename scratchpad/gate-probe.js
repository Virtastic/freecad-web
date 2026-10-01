// SPDX-License-Identifier: LGPL-2.1-or-later
// Copyright (c) Virtastic
// Why did the browser-support wall appear? Re-runs the gate's own probe in a real browser
// and reports which of its three conditions failed.
//
//   node scratchpad/gate-probe.js [url]
//
// The gate refuses a browser that cannot run this build, and it does so by compiling a
// 56-byte memory64 module and calling it through WebAssembly.promising with a BigInt. A
// gate that refuses a browser which could actually run the app is itself a bug -- so the
// question is which condition trips, and in which browser.
const { spawn } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');

const URL_ = process.argv[2] || 'https://cad.search.dontexist.com/';
const HEADLESS = process.argv.includes('--headful') ? false : true;
const CHROME = process.env.CHROME_PATH || '/usr/local/bin/chrome';
const PORT = 9800 + (process.pid % 400);
const PROFILE = fs.mkdtempSync(path.join(os.tmpdir(), 'fcgate-'));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// The gate's probe, verbatim from play-gui/freecad-gui.html.
const PROBE = `
(function(){
  var out = {};
  out.ua = navigator.userAgent;
  out.isSecureContext = window.isSecureContext;
  out.crossOriginIsolated = window.crossOriginIsolated;
  out.hasSAB = typeof SharedArrayBuffer === 'function';
  out.hasSuspending = typeof WebAssembly.Suspending === 'function';
  out.hasPromising = typeof WebAssembly.promising === 'function';
  out.hasMemory64 = (function(){
    try { return new WebAssembly.Memory({initial:1, index:'i64'}); } catch(e){ return 'ERR '+e.name; }
  })();

  var PROBE_BYTES = new Uint8Array([0,97,115,109,1,0,0,0,1,6,1,96,1,126,1,126,2,12,1,3,101,110,118,4,
    119,97,105,116,0,0,3,2,1,0,5,3,1,4,1,7,5,1,1,102,0,1,10,8,1,6,0,32,0,16,0,11]);
  try {
    var mod = new WebAssembly.Module(PROBE_BYTES);
    var inst = new WebAssembly.Instance(mod, { env: { wait: function(v){ out.roundTrip = v; return v; } } });
    out.instantiated = true;
    var mod2 = new WebAssembly.Module(PROBE_BYTES);
    var inst2 = new WebAssembly.Instance(mod2, {
      env: { wait: new WebAssembly.Suspending(function(v){ return v; }) }
    });
    out.suspendingWrap = true;
    // (a) the BigInt round trip
    var p = inst2.exports.f.promise(42n);
    out.promisedType = typeof p.then === 'function' ? 'promise' : typeof p;
    if (out.promisedType === 'promise') {
      Promise.resolve(p).then(function(v){ out.roundTrip = v; });
    }
    // (b) a Number must be REJECTED
    try {
      var p2 = inst2.exports.f.promise(42);
      out.numberRejected = false;
      if (p2 && p2.catch) { p2.catch(function(){ out.numberRejected = true; }); }
      else if (p2 && typeof p2.then === 'function') { out.numberRejected = false; }
    } catch (e) { out.numberRejected = true; out.numberErr = e.name; }
  } catch (e) {
    out.instantiateErr = (e && e.name) + ': ' + (e && e.message);
  }
  return out;
})()
`;

class CDP {
  constructor(ws) {
    this.ws = ws; this.id = 0; this.pending = new Map();
    ws.addEventListener('message', (ev) => {
      let m; try { m = JSON.parse(ev.data); } catch (e) { return; }
      if (m.id && this.pending.has(m.id)) {
        const { resolve, reject } = this.pending.get(m.id);
        this.pending.delete(m.id);
        m.error ? reject(new Error(JSON.stringify(m.error))) : resolve(m.result);
      }
    });
  }
  send(method, params) {
    const id = ++this.id;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.ws.send(JSON.stringify({ id, method, params: params || {} }));
      setTimeout(() => { if (this.pending.has(id)) { this.pending.delete(id); reject(new Error('timeout ' + method)); } }, 120000);
    });
  }
  async evalJs(expression) {
    const r = await this.send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
    if (r.exceptionDetails) throw new Error('eval: ' + (r.exceptionDetails.text || '') + ' ' +
      JSON.stringify(r.exceptionDetails.exception || {}).slice(0, 200));
    return r.result ? r.result.value : undefined;
  }
}

async function main() {
  const args = ['--remote-debugging-port=' + PORT, '--user-data-dir=' + PROFILE,
    '--no-sandbox', '--disable-dev-shm-usage', '--window-size=1600,1000', 'about:blank'];
  if (HEADLESS) args.unshift('--headless=new');
  const child = spawn(CHROME, args, { stdio: ['ignore', 'pipe', 'pipe'] });
  let stderr = ''; child.stderr.on('data', (d) => { stderr += d; });

  let ver = null;
  for (let i = 0; i < 60; i++) {
    await sleep(500);
    try { ver = await (await fetch('http://127.0.0.1:' + PORT + '/json/version')).json(); if (ver.webSocketDebuggerUrl) break; }
    catch (e) {}
  }
  if (!ver) { console.log('chrome never came up'); console.log(stderr.slice(-800)); child.kill(); process.exit(2); }
  console.log('browser : ' + ver.Browser);
  console.log('mode    : ' + (HEADLESS ? 'headless=new' : 'headful'));

  const ws = new WebSocket(ver.webSocketDebuggerUrl);
  await new Promise((res, rej) => { ws.addEventListener('open', res); ws.addEventListener('error', rej); });
  const top = new CDP(ws);
  const { targetId } = await top.send('Target.createTarget', { url: 'about:blank' });
  const list = await (await fetch('http://127.0.0.1:' + PORT + '/json/list')).json();
  const pg = list.find((t) => t.id === targetId);
  const pws = new WebSocket(pg.webSocketDebuggerUrl);
  await new Promise((res, rej) => { pws.addEventListener('open', res); pws.addEventListener('error', rej); });
  const P = new CDP(pws);
  await P.send('Runtime.enable');
  await P.send('Page.enable');

  console.log('\nnavigating to ' + URL_);
  await P.send('Page.navigate', { url: URL_ });
  await sleep(9000);

  const probe = await P.evalJs(PROBE);
  console.log('\ngate probe in this browser:');
  Object.keys(probe).forEach((k) => console.log('  ' + k.padEnd(18) + ' ' + JSON.stringify(probe[k])));

  const wall = await P.evalJs(`(function(){
    var w = document.getElementById('wall');
    return w ? (w.innerText || w.textContent || '').slice(0, 400) : '(no #wall element)';
  })()`).catch((e) => 'ERR ' + e);
  console.log('\nwall element:\n  ' + String(wall).replace(/\s+/g, ' ').slice(0, 400));

  const bodyText = await P.evalJs('document.body ? document.body.innerText.slice(0,300) : ""').catch(() => '');
  console.log('\nvisible text:\n  ' + String(bodyText).replace(/\s+/g, ' ').slice(0, 300));

  ws.close(); pws.close(); child.kill('SIGKILL');
  try { fs.rmSync(PROFILE, { recursive: true, force: true }); } catch (e) {}
  process.exit(0);
}
main().catch((e) => { console.error('probe error:', e && e.stack || e); process.exit(2); });
