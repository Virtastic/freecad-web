// SPDX-License-Identifier: LGPL-2.1-or-later
// Copyright (c) Virtastic
// Server files (issue #8): the page half, driven against a REAL session service.
//
//   node scratchpad/serverfiles.js                 # the checks that need no server
//   FCWEB_FILES_URL=http://127.0.0.1:8099 node scratchpad/serverfiles.js --live
//
// No browser is available here, so rather than a page this extracts the actual block out
// of play-gui/freecad-gui.html and runs it in a vm with a stub DOM and the real fetch.
// That way the shipped code is what runs: a rename or a typo in the HTML fails here
// exactly as it would in a tab. Every assertion below goes through window.fcwebServerFiles
// -- nothing reaches into the block's private scope, because a test that can do that is a
// test that keeps passing after the code stops working.
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const http = require('http');

const HTML = path.resolve(__dirname, '../play-gui/freecad-gui.html');

// ---- pull the block out of the page -------------------------------------------------
function extract() {
  const src = fs.readFileSync(HTML, 'utf8');
  const a = src.indexOf('// ---- Server files (opt-in) ---');
  if (a < 0) throw new Error('server-files block not found in the page');
  // End just before the next function that belongs to the open/save machinery, so the
  // export inside the block is included -- it is the last statement of the block.
  const b = src.indexOf('function openFile(filter){', a);
  if (b < 0) throw new Error('end of the server-files block not found');
  const block = src.slice(a, b);
  if (!block.includes('window.fcwebServerFiles')) throw new Error('block exports nothing');
  return block;
}

// ---- the minimum the block touches ----------------------------------------------------
function stubEl() {
  return {
    style: {}, classList: { add() {}, remove() {} }, children: [],
    _text: '', _html: '', _onclick: null, _disabled: false, title: '',
    get textContent() { return this._text; },
    set textContent(v) { this._text = String(v); this.children.length = 0; },
    get innerHTML() { return this._html; }, set innerHTML(v) { this._html = v; },
    appendChild(c) { this.children.push(c); return c; },
    removeChild(c) { const i = this.children.indexOf(c); if (i >= 0) this.children.splice(i, 1); },
    remove() {}, addEventListener() {}, setAttribute() {}, click() {}, focus() {}
  };
}

// A document good enough for the panel builder: it creates real elements, sets textContent
// and style on them, appends them, and calls requestAnimationFrame. Without createElement
// the build path threw before reaching any of the logic under test.
function stubDoc() {
  const doc = stubEl();
  doc.createElement = () => stubEl();
  doc.getElementById = () => null;
  doc.addEventListener = () => {};
  doc.removeEventListener = () => {};
  doc.querySelector = () => null;
  doc.querySelectorAll = () => [];
  doc.hidden = false;
  return doc;
}

// A localStorage per instance, so two "browsers" really are two browsers.
function makeStorage(seed) {
  const m = new Map(Object.entries(seed || {}));
  return {
    getItem: (k) => (m.has(k) ? m.get(k) : null),
    setItem: (k, v) => m.set(k, String(v)),
    removeItem: (k) => m.delete(k),
    clear: () => m.clear(),
    _dump: () => Object.fromEntries(m)
  };
}

// Every fetch the block makes is recorded, so a claim like "this makes no request" is
// checked rather than assumed.
function makeSandbox(opts = {}) {
  const storage = opts.storage || makeStorage();
  const toasts = [];
  const notes = [];
  const doc = stubDoc();
  doc.body = stubEl();
  const calls = [];
  const sandbox = {
    document: doc, localStorage: storage, location: { search: '' }, console,
    setTimeout, clearTimeout, setInterval: () => 0, clearInterval,
    URL: { createObjectURL: () => 'blob:', revokeObjectURL() {} },
    Blob: class {}, TextEncoder, TextDecoder,
    requestAnimationFrame: (fn) => fn(),
    // The block mints its namespace with crypto.getRandomValues. Without this the key is
    // null and EVERY request short-circuits, which would make the "makes no request"
    // assertions below pass without proving anything.
    crypto: require('crypto').webcrypto,
    // Members the block closes over from the script it lives inside.
    ready: () => !!opts.ready,
    py: (src) => { (opts.py || []).push(src); return true; },
    append: (m) => notes.push(m),
    stageFiles: () => [],
    pickMaster: () => null,
    watchForMissingLinks: () => {},
    fcInstance: opts.ready
      ? { FS: { writeFile: (p, b) => (opts.written || []).push([p, b.length]), mkdirTree() {} } }
      : null,
    UP: '/home/web_user/_up'
  };
  sandbox.window = sandbox;
  sandbox.globalThis = sandbox;
  sandbox.__calls = calls;
  // Record EVERY fetch, then delegate. Wrapping rather than replacing: a harness that only
  // counts calls when it supplied its own fetch would report "no request" for a request it
  // was too busy to see, which is how a gate test passes without testing the gate.
  sandbox.fetch = (p, i) => {
    calls.push([(i && i.method) || 'GET', p]);
    if (opts.fetch) { return opts.fetch(p, i); }
    return Promise.reject(new Error('no fetch stub in this sandbox'));
  };
  sandbox.fcwebNotify = (t, k) => toasts.push({ text: String(t), kind: k });
  sandbox.window.fcwebNotify = sandbox.fcwebNotify;
  return { sandbox, toasts, notes, storage, calls };
}

function load(opts) {
  const parts = makeSandbox(opts);
  vm.runInContext(extract(), vm.createContext(parts.sandbox), { filename: 'server-files-block.js' });
  const api = parts.sandbox.window.fcwebServerFiles;
  if (!api) throw new Error('the block did not export window.fcwebServerFiles');
  return Object.assign(parts, { api });
}

// ---- assertions ------------------------------------------------------------------------
let pass = 0, fail = 0;
const failures = [];
function ok(cond, what) {
  if (cond) { pass++; console.log('  ok   ' + what); }
  else { fail++; failures.push(what); console.log('  FAIL ' + what); }
}
const eq = (a, b, what) => ok(a === b, what + ' (got ' + JSON.stringify(a) + ')');

// ---- checks that need no server --------------------------------------------------------
async function offline() {
console.log('server files, page half, no server:');

// The gate that matters most: this is the promise the whole site makes.
{
  const t = load();
  eq(t.api.enabled(), false, 'a fresh browser has it off');
  t.api.onSave('/home/web_user/_dl/Box.FCStd', new Uint8Array([1, 2, 3]));
  eq(t.calls.length, 0, 'onSave with the feature off makes NO request');
}

// Off is also the answer for a site that has no file store: a 404 must not be an error.
{
  const t = load({
    fetch: () => Promise.resolve({
      status: 404, ok: false, text: () => Promise.resolve('{"code":"files_off"}')
    })
  });
  let threw = false, r;
  try { r = await t.api.available(); } catch (e) { threw = true; }
  eq(r, false, 'a 404 answer means "off", not an error');
  ok(!threw, 'and does not reject');
}

// The namespace is minted once and reused. Minting per call would address a different,
// always-empty folder each time -- which looks exactly like losing every document.
{
  const t = load();
  const first = t.api.ns();
  eq(first, t.api.ns(), 'the namespace key is stable across calls');
  eq(first, t.storage.getItem('fcweb-files-ns'), 'and it is the one in storage');
  ok(/^[0-9a-f]{32}$/.test(first), 'it is 32 hex, the shape the server requires');
}
// Two browsers must not share it.
{
  const a = load(), b = load();
  ok(a.api.ns() !== b.api.ns(), 'two browsers get different keys');
}

// A corrupt stored key must be replaced rather than sent: the server would refuse it and
// the page would report "no folder" with nothing the user could do about it.
{
  const t = load({ storage: makeStorage({ 'fcweb-files-ns': 'not-a-key' }) });
  const k = t.api.ns();
  ok(/^[0-9a-f]{32}$/.test(k), 'a corrupt stored key is replaced with a valid one');
  eq(t.api.ns(), k, 'and then stays put');
}
// No crypto means no key, and that is a refusal, never a shared fallback.
{
  const parts = makeSandbox({ fetch: () => Promise.resolve({ status: 404, ok: false, text: () => Promise.resolve('{}') }) });
  const s = parts.sandbox;
  delete s.crypto;
  vm.runInContext(extract(), vm.createContext(s), { filename: 'no-crypto' });
  eq(s.window.fcwebServerFiles.ns(), null, 'no crypto yields no key, not a fake one');
}

// enable() is the one thing that changes the gate, and it is per browser.
{
  const a = load(), b = load();
  a.api.enable(true);
  eq(a.api.enabled(), true, 'enable() turns it on for this browser');
  eq(b.api.enabled(), false, 'and not for another');
  a.api.enable(false);
  eq(a.api.enabled(), false, 'enable(false) turns it back off');
}

// What the save watcher hands us.
{
  const t = load();
  eq(t.api.name('/home/web_user/_dl/Box.FCStd'), 'Box.FCStd', 'name is the basename');
  eq(t.api.name('/home/web_user/_up/a/b/Part-1.FCStd'), 'Part-1.FCStd', 'and handles nesting');
  eq(t.api.size(512), '512 B', '512 bytes reads as bytes');
  eq(t.api.size(2048), '2 KB', '2048 reads as KB');
  eq(t.api.size(5 * 1048576), '5.0 MB', '5 MB reads as MB');
  eq(t.api.size(3 * 1073741824), '3.0 GB', '3 GB reads as GB');
}

// Enabling without a confirmed site must still not write: two independent gates.
{
  const t = load({
    fetch: () => Promise.resolve({
      status: 200, ok: true, text: () => Promise.resolve('{"files":[]}')
    })
  });
  t.api.enable(true);
  t.api.onSave('/home/web_user/_dl/Box.FCStd', new Uint8Array([1]));
  eq(t.calls.length, 0, 'enabled but site unconfirmed: still no request');
  await t.api.available();
  ok(t.calls.length >= 1, 'available() is what asks the server, once');
  const before = t.calls.length;
  await t.api.available();
  eq(t.calls.length, before, 'and the answer is cached, not re-asked');
}

// Confirmed and enabled: the save watcher now reaches the server.
// The stub answers by METHOD, because the availability probe is a GET /files whose body
// must contain a `files` array -- a save-shaped body makes the page read the site as
// unavailable, and then correctly refuses to save. That distinction is the feature's
// whole off-switch, so the stub has to respect it.
{
  const t = load({
    fetch: (p, i) => {
      const m = (i && i.method) || 'GET';
      return Promise.resolve({
        status: 200, ok: true,
        text: () => Promise.resolve(m === 'GET'
          ? '{"files":[],"used":0,"quota":2147483648,"max_mb":25}'
          : '{"ok":true,"name":"Box.FCStd","bytes":3}')
      });
    }
  });
  t.api.enable(true);
  eq(await t.api.available(), true, 'the site reads as available');
  const before = t.calls.length;
  t.api.onSave('/home/web_user/_dl/Box.FCStd', new Uint8Array([1, 2, 3]));
  eq(t.calls.length, before + 1, 'confirmed + enabled: exactly one request per save');
  eq(t.calls[t.calls.length - 1][0], 'PUT', 'and it is a PUT');
  ok(t.calls[t.calls.length - 1][1].indexOf('/files/Box.FCStd') >= 0, 'to the document URL');
}

// BOTH save paths must copy to the server. Found by the manual pass on 2026-10-01:
// plain File > Save and Ctrl+S land in download(), which had no reference to the server
// copy at all -- only Save As / Export do, because those go through getSaveFileName and
// are announced by registerSave() into the save watcher. The symptom was a document that
// synced after Save As and then never updated again however often it was saved.
//
// download() lives in a different script block from the one this harness extracts, so it
// cannot be called here. What CAN be asserted, and what would have caught it, is that the
// function body itself reaches the server copy -- parsed out of the real file rather than
// grepped, so the watcher's call cannot mask its absence.
{
  const src = fs.readFileSync(HTML, 'utf8');
  const m = src.match(/  async function download\(\)\{[\s\S]*?\n  \}\n/);
  ok(!!m, 'download() is still present in the page');
  if (m) {
    ok(m[0].indexOf('fcwebServerFiles.onSave') > 0,
       'download() -- the File > Save / Ctrl+S path -- copies to the server');
    // It must pass the bytes it just handed to the browser. Re-reading the staged file
    // cannot work: download() unlinks it before returning.
    ok(/onSave\(.*bytes\)/.test(m[0]), 'and passes the bytes, not a path to re-read');
  }
}

// ...and the whole thing stays off if the site has no store, even once enabled.
{
  const t = load({
    fetch: () => Promise.resolve({
      status: 404, ok: false, text: () => Promise.resolve('{"code":"files_off"}')
    })
  });
  t.api.enable(true);
  eq(await t.api.available(), false, 'a site with no store reads as unavailable');
  const before = t.calls.length;
  t.api.onSave('/home/web_user/_dl/Box.FCStd', new Uint8Array([1, 2, 3]));
  eq(t.calls.length, before, 'and a save on such a site writes nothing');
}

// 404 is TWO different answers, and conflating them is what told a user on a server with
// FCWEB_FILES=1 that the operator had not enabled it. files_off = the feature is off;
// no_namespace = the feature is ON and this browser has named no folder, which is exactly
// what a second browser looks like before its folder key is pasted.
//
// Asserted on the TOAST, because that string is what misled the user: with a key
// configured, a browser that has not pasted one was told "ask the operator to start it with
// FCWEB_FILES=1" -- an env var that was already set. The two cases must not share a message.
{
  const mk = (code) => load({
    fetch: () => Promise.resolve({
      status: 404, ok: false,
      text: () => Promise.resolve('{"error":"x","code":"' + code + '","hint":"h"}')
    })
  });
  const say = (t) => t.toasts.map((x) => x.text).join(' | ');

  const off = mk('files_off');
  await off.api.list();
  ok(/FCWEB_FILES=1/.test(say(off)), 'feature genuinely off: the toast names the env var');
  eq(off.sandbox.document.body.children.length, 0, 'and no panel is opened');

  // The right answer to no_namespace is the PANEL, not a toast: the panel holds the folder
  // key field, so opening it is how the user fixes this. Asserted on the panel's own text,
  // since that is what the user reads.
  const ns = mk('no_namespace');
  await ns.api.list();
  ok(ns.sandbox.document.body.children.length > 0,
     'no_namespace opens the panel, because that is where the key is entered');
  ok(/FCWEB_FILES=1/.test(say(ns)) === false,
     'and must NOT tell the user to set an env var that is already set');
  const texts = (function walk(n, out) {
    // stubEl() keeps the textContent setter's value in _text, not _t.
    (n.children || []).forEach((c) => { if (c._text) out.push(c._text); walk(c, out); });
    return out;
  })(ns.sandbox.document.body, []);
  const panel = texts.join(' | ');
  ok(/folder key/i.test(panel), 'and the panel says a folder key is what is missing (' + panel.slice(0, 120) + ')');
}

// The raw error must still carry WHICH 404 it was, because three handlers branch on it.
{
  const src = fs.readFileSync(HTML, 'utf8');
  const n = (src.match(/e\.noFolder=!e\.off/g) || []).length;
  ok(n >= 2, 'both fetch paths set the noFolder flag (' + n + ')');
  ok(/e\.off=!!\(j&&j\.code===\x27files_off\x27\)/.test(src),
     'and neither treats every 404 as "feature off"');
}

// The one that would have bitten a second browser: a shared-key server answers 404 to a
// browser that has not pasted the key, and that must not read as "the feature is off".
{
  const t = load({
    fetch: () => Promise.resolve({
      status: 404, ok: false,
      text: () => Promise.resolve(
        '{"error":"no namespace","code":"no_namespace","hint":"paste the folder key"}')
    })
  });
  const before = t.calls.length;
  t.api.onSave('/home/web_user/_dl/Box.FCStd', new Uint8Array([1, 2, 3]));
  eq(t.calls.length, before, 'a save never happens without a confirmed site');
}

// The panel must survive being opened twice. Found on 2026-10-01 by the manual pass:
// clicking Open threw "something went wrong" because the close helper called .remove() on
// the HANDLE object rather than its element, so the document never opened. Reopening is
// the shortest public-API path through that code -- build() closes any existing panel --
// and with the bug it throws on the second call.
{
  const t = load({
    fetch: (p, i) => {
      const m = (i && i.method) || 'GET';
      return Promise.resolve({
        status: 200, ok: true,
        text: () => Promise.resolve(m === 'GET'
          ? '{"files":[{"name":"Bracket.FCStd","bytes":3,"saved":1700000000}],"used":3,"quota":2147483648,"max_mb":25}'
          : '{"ok":true}')
      });
    }
  });
  let threw = null;
  try {
    await t.api.list();          // first open
    await t.api.list();          // second open: build() closes the first
  } catch (e) { threw = e; }
  ok(!threw, 'opening the panel twice does not throw (' + (threw && threw.message) + ')');
}

// The offer's wording is part of its contract: "here" was reported as ambiguous, and the
// dialog stayed up after being answered. Scoped to a BUTTON LABEL -- the phrase survives in
// a comment explaining the change, so a bare search for the words proves nothing.
{
  const src = fs.readFileSync(HTML, 'utf8');
  ok(!/label: *['"]Keep documents here/.test(src), 'the ambiguous "here" label is gone');
  ok(/label: *['"]Send copies to the server/.test(src), 'the button names the server explicitly');
  ok(/dismissOnAction/.test(src), 'the offer dismisses once answered');
}
}

// ---- live: drive a real session service --------------------------------------------------
function req(base, method, p, body, ns) {
  return new Promise((resolve, reject) => {
    const u = new URL(p, base);
    const headers = ns ? { 'X-Fcweb-Ns': ns } : {};
    // Content-Length explicitly. Without it Node sends the body chunked, and the stdlib
    // http.server behind `share.py --serve` reads only Content-Length -- so it would see a
    // 0-byte body, answer 413, and then fail to parse whatever came next on that socket.
    // A browser always sets it for a Uint8Array body, so this is the harness that has to
    // behave like the browser rather than the server that has to be lenient.
    if (body) headers['Content-Length'] = Buffer.byteLength(body);
    const r = http.request({
      hostname: u.hostname, port: u.port, path: u.pathname + u.search, method, headers
    }, (res) => {
      const chunks = [];
      res.on('data', (c) => chunks.push(c));
      res.on('end', () => resolve({ status: res.statusCode, body: Buffer.concat(chunks) }));
    });
    r.on('error', reject);
    if (body) r.write(body);
    r.end();
  });
}

function liveFetch(base, sink) {
  return (p, init) => {
    const m = (init && init.method) || 'GET';
    if (sink) sink.push([m, p]);
    const ns = init && init.headers && init.headers['X-Fcweb-Ns'];
    return req(base, m, p, init && init.body, ns).then((r) => ({
      status: r.status,
      ok: r.status >= 200 && r.status < 300,
      text: () => Promise.resolve(r.body.toString('utf8')),
      arrayBuffer: () => Promise.resolve(r.body.buffer.slice(r.body.byteOffset,
        r.body.byteOffset + r.body.byteLength))
    }));
  };
}

function api(base, opts) {
  // A fresh namespace per run, so a re-run never collides with a previous one's folder.
  const ns = require('crypto').randomBytes(16).toString('hex');
  const t = load(Object.assign({ storage: makeStorage({ 'fcweb-files-ns': ns }),
    fetch: liveFetch(base, (opts || {}).calls) }, opts || {}));
  t.ns = ns;
  t.raw = (method, p, body) => req(base, method, p, body, ns);
  t.list = async () => JSON.parse((await t.raw('GET', '/files')).body).files;
  return t;
}

async function live(base) {
  console.log('\nserver files against ' + base + ':');
  const A = api(base);
  const B = api(base);

  eq(await A.api.available(), true, 'a site with the feature on reports available');
  eq(A.api.enabled(), false, 'and the browser still has it off until asked');
  A.api.enable(true);
  eq(A.api.enabled(), true, 'after enable()');

  const doc = Buffer.from('FCStd-doc-bytes-0123456789', 'binary');
  const r = await A.api.save('/home/web_user/_dl/Bracket.FCStd', doc);
  ok(r && r.name === 'Bracket.FCStd', 'save() reports the name back');
  eq(r.bytes, doc.length, 'save() reports the byte count');

  let files = await A.list();
  eq(files.length, 1, 'the folder holds one document');
  eq(files[0].name, 'Bracket.FCStd', 'named after the saved file');

  const got = await A.raw('GET', '/files/Bracket.FCStd');
  ok(got.body.equals(doc), 'the bytes round-trip exactly');

  eq((await B.list()).length, 0, 'a second browser sees an empty folder');
  eq((await B.raw('GET', '/files/Bracket.FCStd')).status, 404, 'and cannot read the file');

  // Unicode: what a CAD user actually types.
  const uni = Buffer.from('Ünter Rad über.FCStd', 'binary');
  await A.api.save('/home/web_user/_dl/Ünter Rad über.FCStd', uni);
  files = await A.list();
  ok(files.some((f) => f.name === 'Ünter Rad über.FCStd'), 'an accented name is stored and listed');
  ok((await A.raw('GET', '/files/' + encodeURIComponent('Ünter Rad über.FCStd'))).body.equals(uni),
     'and its bytes round-trip');

  // Re-save replaces rather than duplicating.
  await A.api.save('/home/web_user/_dl/Bracket.FCStd', Buffer.from('v2', 'binary'));
  files = await A.list();
  eq(files.filter((f) => f.name === 'Bracket.FCStd').length, 1, 'a re-save is one entry');
  eq(files.find((f) => f.name === 'Bracket.FCStd').bytes, 2, 'holding the new bytes');

  // A save arriving while one is in flight must not be dropped: dropping it leaves the
  // server on the previous version, which is the failure this feature exists to prevent.
  await Promise.all([0, 1, 2, 3, 4].map((i) =>
    A.api.save('/home/web_user/_dl/Race.FCStd', Buffer.from('gen' + i, 'binary'))));
  eq((await A.raw('GET', '/files/Race.FCStd')).body.toString('binary'), 'gen4',
     'concurrent saves end on the newest bytes');

  // Oversized, refused, and nothing lost.
  const big = (await A.raw('GET', '/files')).status;
  eq(big, 200, 'the listing is still readable after all of that');
  const over = await A.raw('PUT', '/files/Over.FCStd', Buffer.alloc(64 * 1048576));
  ok(over.status === 413 || over.status === 507, 'an oversized save is refused (' + over.status + ')');
  ok((await A.list()).some((f) => f.name === 'Bracket.FCStd'), 'and the refusal kept what was there');

  // Traversal is a bad request, never a read of anything else on the box.
  eq((await A.raw('PUT', '/files/' + encodeURIComponent('../../etc/passwd'), 'x')).status, 400,
     'a traversal name is refused');
  eq((await A.raw('PUT', '/files/' + encodeURIComponent('.hidden'), 'x')).status, 400,
     'a dotfile name is refused');

  // Delete, then a second delete is a miss rather than a silent success.
  await A.api.del('Bracket.FCStd');
  ok(!(await A.list()).some((f) => f.name === 'Bracket.FCStd'), 'del() removes it');
  const again = await A.raw('DELETE', '/files/Bracket.FCStd');
  eq(again.status, 404, 'deleting it again is a miss');
  ok(JSON.parse(again.body).hint, 'and the miss carries a hint, as every error here does');

  // A site with the feature OFF must read as "off" rather than failing.
  const dead = load({ fetch: () => Promise.resolve({
    status: 404, ok: false, text: () => Promise.resolve('{"code":"files_off","hint":"nope"}')
  }) });
  eq(await dead.api.available(), false, 'a 404 site reports not available');
  const dead2 = load({ fetch: () => Promise.resolve({
    status: 502, ok: false, text: () => Promise.resolve('<html>502 Bad Gateway</html>')
  }) });
  eq(await dead2.api.available(), false, 'a site with no session service at all also reports not available');
}
// ---- run ---------------------------------------------------------------------------------
(async () => {
  await offline();
  if (process.argv.includes('--live')) {
    const base = process.env.FCWEB_FILES_URL;
    if (!base) {
      console.error('\nset FCWEB_FILES_URL, e.g. FCWEB_FILES_URL=http://127.0.0.1:8099');
      process.exit(2);
    }
    await live(base.replace(/\/$/, ''));
  }
  console.log('\n' + pass + ' passed, ' + fail + ' failed');
  if (failures.length) { console.log('failed:'); failures.forEach((f) => console.log('  - ' + f)); }
  process.exit(fail ? 1 : 0);
})().catch((e) => { console.error('harness error:', e && e.stack || e); process.exit(1); });