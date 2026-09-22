// Does the Lens add-on (FreeCAD/Ondsel-Lens-Addon) work in the browser build?
//
// Installs it through the Addon Manager as the catalogue lists it (name Ondsel-Lens,
// branch main; GitHub serves the renamed branch as a "-develop" wrapper folder) (its deps pyjwt, requests, tzlocal arrive as
// pure wheels via fcweb_wheels), then drives the add-on's OWN APIClient against the
// live api.lens.freecad.org through fcweb_requests (requests over QtNetwork, direct
// CORS, no proxy):
//   1. `requests` is hooked onto QtNetwork once the wheel lands
//   2. APIClient online check (GET /) reports the server reachable
//   3. getSharedModels(): a real JSON list of public share links (unauthenticated read)
//   4. authenticate() with a bad password -> the add-on's own
//      APIClientAuthenticationException (a POST with a JSON body round-tripped and
//      the 401 was parsed), NOT a connection error
//   5. with LENS_EMAIL / LENS_PASSWORD in the environment: real login, then
//      getWorkspaces() lists the account's workspaces
//   node scratchpad/lens.js http://127.0.0.1:8792/freecad-gui.html
const puppeteer = require('puppeteer-core');
const sl = (ms) => new Promise((r) => setTimeout(r, ms));
const NL = String.fromCharCode(10);
const URL = process.argv[2] || 'http://127.0.0.1:8792/freecad-gui.html';
const CHROME = process.env.CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const EMAIL = process.env.LENS_EMAIL || '', PASS = process.env.LENS_PASSWORD || '';
let fails = 0;
const ok = (c, m) => { console.log((c ? '  ok   ' : '  FAIL ') + m); if (!c) fails++; };
const runPy = (p, c) => p.evaluate((c) => { const m = window.fcInstance; const n = new TextEncoder().encode(c).length + 1; const q = m._malloc(n); m.stringToUTF8(c, q, n); (window.fcRunPy)(m, q); }, c);
const waitMarker = async (p, marker, ms) => {
  const t = Date.now();
  while (Date.now() - t < ms) {
    const log = await p.evaluate(() => (document.getElementById('log') || {}).textContent || '');
    const m = log.match(new RegExp('(?:^|\\n)(?:\\{[^}]*\\} )?(' + marker + ') ([^\\n]*)'));
    if (m) return m[2];
    await sl(1500);
  }
  return null;
};
const J = (s) => { try { return JSON.parse(s); } catch (e) { return null; } };
// Results go to files in the wasm FS: the page log is a capped ring and evicts one-shot
// markers under install noise (measured; see memory 'gates that grep the log').
const waitFile = async (p, path, ms) => {
  const t = Date.now();
  while (Date.now() - t < ms) {
    const s = await p.evaluate((path) => { try { return window.fcInstance.FS.readFile(path, { encoding: 'utf8' }); } catch (e) { return null; } }, path);
    if (s) return s;
    await sl(1500);
  }
  return null;
};

(async () => {
  const b = await puppeteer.launch({ executablePath: CHROME, headless: true, defaultViewport: { width: 1400, height: 900 },
    args: ['--no-sandbox', '--use-gl=angle'], protocolTimeout: 1200000, userDataDir: 'C:/Users/MICHAE~1/AppData/Local/Temp/fc-lens-' + Date.now() });
  const p = (await b.pages())[0];
  const cors = [];
  p.on('requestfailed', r => { if (/lens\.freecad/.test(r.url())) cors.push('FAILED ' + r.method() + ' ' + r.url() + ' ' + (r.failure() || {}).errorText); });
  p.on('response', r => { if (/lens\.freecad/.test(r.url())) cors.push(r.status() + ' ' + r.request().method() + ' ' + r.url().slice(0, 90)); });
  await p.goto(URL, { waitUntil: 'domcontentloaded', timeout: 300000 });
  const t = Date.now();
  while (Date.now() - t < 420000) { if (await p.evaluate(() => !!window.__fcWorkReady && !!(window.fcInstance && window.fcInstance._malloc))) break; await sl(1000); }
  await sl(10000);
  ok((await waitMarker(p, '\\[fcweb\\] addon-manager: requests', 90000)) !== null, 'overlay loaded fcweb_requests');

  // Install the Lens add-on: deps through DependencyInstaller, then the add-on itself.
  await runPy(p, [
    'import sys, json',
    'try:',
    '    import addonmanager_dependency_installer as D',
    '    from Addon import Addon',
    '    _a = Addon("Ondsel-Lens", "https://github.com/FreeCAD/Ondsel-Lens-Addon", Addon.Status.NOT_INSTALLED, "main")',
    '    _inst = D.DependencyInstaller([], ["pyjwt", "requests", "tzlocal"], [])',
    '    _ldr = {}',
    '    def _f(a, b): _ldr["failure"] = (a, b)',
    '    def _d(okv):',
    '        _ldr["finished"] = okv; open("/tmp/lens-deps.json", "w").write(json.dumps(_ldr))',
    '    _inst.failure.connect(_f); _inst.finished.connect(_d); sys._ldep = _inst; _inst.run()',
    'except Exception as e:',
    '    import traceback; open("/tmp/lens-deps.json", "w").write(json.dumps({"exc": traceback.format_exc()}))',
  ].join(NL));
  const deps = J(await waitFile(p, '/tmp/lens-deps.json', 300000)) || {};
  ok(deps.finished === true && !deps.failure, 'pyjwt, requests, tzlocal installed: ' + JSON.stringify(deps));

  await runPy(p, [
    'import sys, json',
    'try:',
    '    from addonmanager_installer import AddonInstaller',
    '    from Addon import Addon',
    '    _a = Addon("Ondsel-Lens", "https://github.com/FreeCAD/Ondsel-Lens-Addon", Addon.Status.NOT_INSTALLED, "main")',
    '    _ai = AddonInstaller(_a); _lar = {}',
    '    _ai.success.connect(lambda x: _lar.__setitem__("success", True)); _ai.failure.connect(lambda x, m: _lar.__setitem__("failure", m))',
    '    def _d(): open("/tmp/lens-addon.json", "w").write(json.dumps(_lar))',
    '    _ai.finished.connect(_d); sys._lai = _ai; _ai.run()',
    'except Exception as e:',
    '    import traceback; open("/tmp/lens-addon.json", "w").write(json.dumps({"exc": traceback.format_exc()}))',
  ].join(NL));
  const ad = J(await waitFile(p, '/tmp/lens-addon.json', 300000)) || {};
  ok(ad.success === true, 'Lens add-on installed: ' + JSON.stringify(ad));

  // A workbench-style add-on is loaded by FreeCAD at startup from its InitGui.py, so
  // reload the page (the install persists in the browser filesystem) and let FreeCAD
  // load Lens exactly as it would for the user. Then drive the add-on's own API client.
  await p.reload({ waitUntil: 'domcontentloaded', timeout: 300000 });
  const t2 = Date.now();
  while (Date.now() - t2 < 420000) { if (await p.evaluate(() => !!window.__fcWorkReady && !!(window.fcInstance && window.fcInstance._malloc))) break; await sl(1000); }
  await sl(10000);
  // The add-on imports requests from its InitGui.py; sitecustomize's import hook prints this.
  ok((await waitMarker(p, '\\[fcweb\\] requests ->', 90000)) !== null, 'requests hooked onto /dev/fcweb-http when the add-on imported it at startup');
  console.log(await p.evaluate(() => { const l = ((document.getElementById('log') || {}).textContent || '').split(String.fromCharCode(10)); return l.filter(x => /Ondsel|Lens|InitGui|lens_command|Traceback|Error/.test(x)).slice(0, 30).map(x => '    boot: ' + x.slice(0, 220)).join(String.fromCharCode(10)); }));
  // FreeCAD's Mod loop prints only the message; the traceback is Log()-level, in its log file.
  console.log(await p.evaluate(() => {
    try {
      const FS = window.fcInstance.FS, dir = '/home/web_user/.local/share/FreeCAD/v1-1';
      const f = FS.readdir(dir).filter(x => /\.log$/i.test(x))[0];
      if (!f) return '    (no FreeCAD log under ' + dir + ': ' + FS.readdir(dir).join(' ') + ')';
      const l = FS.readFile(dir + '/' + f, { encoding: 'utf8' }).split(String.fromCharCode(10));
      const i = l.findIndex(x => /sysconfigdata|Ondsel-Lens.*failed/.test(x));
      return i < 0 ? '    (log ' + f + ': nothing about Ondsel-Lens)' : l.slice(Math.max(0, i - 25), i + 3).map(x => '    log: ' + x.slice(0, 200)).join(String.fromCharCode(10));
    } catch (e) { return '    log read failed: ' + e; }
  }));
  await runPy(p, [
    'import sys, os, json',
    'try:',
    '    import FreeCADGui as Gui',
    '    o = {"lens_command": "OndselLens_OndselLens" in Gui.listCommands(), "initgui_loaded": "lens_command" in sys.modules, "sitecustomize": getattr(sys.modules.get("sitecustomize"), "__file__", None)}',
    '    import traceback',
    '    # what InitGui.py does, step by step, so a failure names its step (FreeCAD only logs the message)',
    '    steps = [("import lens_command", lambda: __import__("lens_command")),',
    '             ("import reloadable", lambda: __import__("integrations.reloadablefile.reloadable")),',
    '             ("import register_lens_handler", lambda: __import__("register_lens_handler")),',
    '             ("start_mdi_tab", lambda: sys.modules["lens_command"].start_mdi_tab()),',
    '             ("init_toolbar_icon", lambda: sys.modules["lens_command"].init_toolbar_icon()),',
    '             ("ensure_mdi_tab", lambda: sys.modules["lens_command"].ensure_mdi_tab()),',
    '             ("register_lens_handler", lambda: sys.modules["register_lens_handler"].register_lens_handler()),',
    '             ("reloadable.initialize", lambda: sys.modules["integrations.reloadablefile.reloadable"].initialize())]',
    '    o["initgui_steps"] = {}',
    '    for name, fn in steps:',
    '        try:',
    '            fn(); o["initgui_steps"][name] = "ok"',
    '        except Exception:',
    '            o["initgui_steps"][name] = traceback.format_exc().replace(chr(10), " | ")[-600:]',
    '    import requests; from requests.sessions import Session',
    '    o["hooked"] = bool(getattr(Session, "_fcweb_hooked", False))',
    '    import APIClient as AC',
    '    class _P: api = None',
    '    c = AC.APIClient(_P(), "", "", "https://api.lens.freecad.org", "https://lens.freecad.org", "freecad-web", "0")',
    '    c._confirm_online(); o["status_after_online_check"] = c.status.name',
    '    import zoneinfo; o["zoneinfo"] = True   # needs the sysconfig data the image never shipped',
    '    pub = {"$limit": 25, "$skip": 0, "$sort[createdAt]": -1, "protection": "Listed", "isActive": "true", "isThumbnailGenerated": "true"}   # get_public_shared_models() params',
    '    sm = c._request("shared-models", {}, pub)["data"]',
    '    o["shared_models"] = len(sm); o["first_title"] = (sm[0].get("title") if sm else None)',
    '    try:',
    '        o["sharelink_parse"] = len(c.get_public_shared_models())',
    '    except Exception as e:',
    '        o["sharelink_parse"] = type(e).__name__ + ": " + str(e)[:120]',
    '    c.email = "nobody@example.invalid"; c.password = "wrong-on-purpose"',
    '    try:',
    '        c.authenticate(); o["bad_login"] = "no exception"',
    '    except AC.APIClientAuthenticationException as e:',
    '        o["bad_login"] = "APIClientAuthenticationException"',
    '    except Exception as e:',
    '        o["bad_login"] = type(e).__name__ + ": " + str(e)[:160]',
    '    em, pw = ' + JSON.stringify(EMAIL) + ', ' + JSON.stringify(PASS),
    '    if em and pw:',
    '        c.email, c.password = em, pw',
    '        c.authenticate(); o["login"] = c.status.name; o["user"] = (c.user or {}).get("email")',
    '        ws = c.getWorkspaces(); o["workspaces"] = [w.get("name") for w in ws]',
    '    open("/tmp/lens-api.json", "w").write(json.dumps(o))',
    'except Exception as e:',
    '    import traceback; o = globals().get("o") or {}; o["exc"] = traceback.format_exc(); open("/tmp/lens-api.json", "w").write(json.dumps(o))',
  ].join(NL));
  const o = J(await waitFile(p, '/tmp/lens-api.json', 120000)) || {};
  console.log('  initgui steps: ' + JSON.stringify(o.initgui_steps));
  if (o.exc) console.log('  api exc: ' + o.exc);
  ok(typeof o.sitecustomize === 'string' && o.sitecustomize.indexOf('site-packages') > 0, 'sitecustomize ran at interpreter start: ' + o.sitecustomize);
  ok(o.lens_command === true && o.initgui_loaded === true, 'FreeCAD loaded the add-on at startup: command registered');
  ok(o.zoneinfo === true, 'import zoneinfo works (sysconfig data present)');
  ok(o.hooked === true, 'Session.send is the Qt transport');
  ok(o.status_after_online_check === 'LOGGED_OUT', 'online check reached the server: ' + o.status_after_online_check);
  ok(typeof o.shared_models === 'number' && o.shared_models > 0, 'public shared-models query via the add-on returned ' + o.shared_models + ' links (first: ' + o.first_title + ')');
  console.log('  (info) ShareLink.from_json over the live API: ' + o.sharelink_parse + '  [add-on data model vs current API; not a transport matter]');
  ok(o.bad_login === 'APIClientAuthenticationException', 'bad password -> the add-on\'s own auth exception: ' + o.bad_login);
  if (EMAIL && PASS) {
    ok(o.login === 'CONNECTED' && o.user === EMAIL, 'real login: ' + o.login + ' as ' + o.user);
    ok(Array.isArray(o.workspaces), 'workspaces: ' + JSON.stringify(o.workspaces));
  } else {
    console.log('  (skip) real login: set LENS_EMAIL and LENS_PASSWORD to run it');
  }
  console.log(cors.slice(0, 8).map(l => '    ' + l).join(NL));
  await b.close();
  console.log(fails ? `${NL}${fails} FAILED` : `${NL}all passed`);
  process.exit(fails ? 1 : 0);
})();
