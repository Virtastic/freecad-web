// Add-on Python dependencies, end to end, through the Addon Manager's own installer.
//
// Boots the page, activates the Addon Manager (which applies the overlay's on-activate
// patches, fcweb_wheels among them), then runs upstream's DependencyInstaller exactly the
// way the GUI's install button does, with:
//   - the History Workbench addon (declares PyYAML, which the image ships: the "already
//     satisfied" path, and the case reported on launch day), and
//   - one required pure-Python package the image does NOT ship (tomli-w): the PyPI
//     index -> wheel -> unzip path through /proxy/pypi and /proxy/pyfiles.
// Then asserts: finished(True) fired, `import yaml` and `import tomli_w` both work, the
// workbench directory landed in Mod, and the vendor dir is on sys.path.
//
//   node scratchpad/amdeps.js https://freecad.dev.virtastic.app/
// Exit 1 on any failed assertion. Needs the proxy keys `pypi` and `pyfiles` on the
// target (infra/nginx.conf), so it runs against a deployed image, not the raw tree.
const puppeteer = require('puppeteer-core');
const sl = (ms) => new Promise((r) => setTimeout(r, ms));
const NL = String.fromCharCode(10);
const URL = process.argv[2] || 'https://freecad.dev.virtastic.app/';
const CHROME = process.env.CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const PKG = process.env.AMDEPS_PKG || 'tomli-w';
const PKG_MOD = process.env.AMDEPS_MOD || 'tomli_w';

const runPy = (p, c) => p.evaluate((c) => {
  const m = window.fcInstance;
  const n = new TextEncoder().encode(c).length + 1;
  const q = m._malloc(n);
  m.stringToUTF8(c, q, n);
  (window.fcRunPy || ((mm, pp) => { mm._fcweb_run_python(pp); mm._free(pp); }))(m, q);
}, c);
const waitMarker = async (p, marker, ms) => {
  const t = Date.now();
  while (Date.now() - t < ms) {
    const log = await p.evaluate(() => (document.getElementById('log') || {}).textContent || '');
    const m = log.match(new RegExp(marker + ' [^\\n]*'));
    if (m) return m[0].slice(marker.length + 1);
    await sl(1500);
  }
  return null;
};

let fails = 0;
const ok = (c, m) => { console.log((c ? '  ok   ' : '  FAIL ') + m); if (!c) fails++; };

(async () => {
  const b = await puppeteer.launch({
    executablePath: CHROME, headless: true, defaultViewport: { width: 1400, height: 900 },
    args: ['--no-sandbox', '--use-gl=angle'], protocolTimeout: 1200000,
    userDataDir: 'C:/Users/MICHAE~1/AppData/Local/Temp/fc-amdeps-' + Date.now(),
  });
  const p = (await b.pages())[0];
  await p.goto(URL, { waitUntil: 'domcontentloaded', timeout: 300000 });
  const t = Date.now();
  while (Date.now() - t < 420000) {
    if (await p.evaluate(() => !!window.__fcWorkReady)) break;
    await sl(1000);
  }
  await sl(10000);

  // 1. Activate the Addon Manager so the overlay's on-activate patches run.
  await runPy(p, [
    'import sys, FreeCADGui as Gui',
    'try:',
    '    Gui.runCommand("Std_AddonMgr")',
    '    sys.__stderr__.write("AMOPEN ok\\n")',
    'except Exception as e:',
    '    sys.__stderr__.write("AMOPEN FAILED %r\\n" % (e,))',
    'sys.__stderr__.flush()',
  ].join(NL));
  ok((await waitMarker(p, 'AMOPEN', 60000)) === 'ok', 'Addon Manager opened');
  await sl(8000);

  // 2. Are the hooks in? (DependencyInstaller.run must be ours now.)
  await runPy(p, [
    'import sys',
    'try:',
    '    import addonmanager_dependency_installer as D, fcweb_wheels as W, NetworkManager as NM',
    '    sys.__stderr__.write("HOOKS %s %s %s\\n" % (D.DependencyInstaller.run is W.run_installer,',
    '        D.DependencyInstaller._verify_pip(None), NM.FCWEB_PROXY_HOSTS.get("pypi.org")))',
    'except Exception as e:',
    '    sys.__stderr__.write("HOOKS FAILED %r\\n" % (e,))',
    'sys.__stderr__.flush()',
  ].join(NL));
  const hooks = await waitMarker(p, 'HOOKS', 30000);
  ok(hooks === 'True True pypi', 'hooks installed: ' + hooks);

  // 3. Drive the installer as the GUI does: an Addon from the catalogue plus a required
  //    package, moveToThread is a no-op in the overlay, run() on started.
  await runPy(p, [
    'import sys, os, json',
    'try:',
    '    import addonmanager_dependency_installer as D',
    '    from Addon import Addon',
    '    from PySideWrapper import QtCore',
    '    from addonmanager_workers_startup import CreateAddonListWorker',
    '    _repo = Addon("HistoryWorkbench", "https://github.com/eblanshey/HistoryWorkbench", Addon.Status.NOT_INSTALLED, "release")',
    '    _inst = D.DependencyInstaller([_repo], ["PyYAML", ' + JSON.stringify(PKG) + '], [])',
    '    _res = {}',
    '    def _fail(a, b): _res["failure"] = (a, b)',
    '    def _done(okv):',
    '        _res["finished"] = okv',
    '        sys.__stderr__.write("DEPDONE " + json.dumps(_res) + "\\n"); sys.__stderr__.flush()',
    '    _inst.failure.connect(_fail); _inst.finished.connect(_done)',
    '    sys._fcweb_depinst = _inst',
    '    _inst.run()',
    '    sys.__stderr__.write("DEPSTART ok\\n")',
    'except Exception as e:',
    '    import traceback; sys.__stderr__.write("DEPSTART FAILED " + traceback.format_exc().replace(chr(10), " | ") + "\\n")',
    'sys.__stderr__.flush()',
  ].join(NL));
  ok((await waitMarker(p, 'DEPSTART', 30000)) === 'ok', 'installer started');
  const done = await waitMarker(p, 'DEPDONE', 240000);
  console.log('  installer result: ' + done);
  let res = {};
  try { res = JSON.parse(done); } catch (e) {}
  ok(res.finished === true, 'finished(True)');
  ok(!res.failure, 'no failure signal');

  // 4. Prove it: imports and files.
  await runPy(p, [
    'import sys, os, json, importlib',
    'try:',
    '    importlib.invalidate_caches()',
    '    import yaml',
    '    import ' + PKG_MOD,
    '    import addonmanager_utilities as U',
    '    _vd = U.get_pip_target_directory()',
    '    _mod = os.path.join(os.path.dirname(_vd), "Mod", "HistoryWorkbench")',
    '    _o = {"yaml": yaml.__version__ if hasattr(yaml, "__version__") else "?", "pkg": getattr(' + PKG_MOD + ', "__file__", "?"),',
    '          "vendor_on_path": _vd in sys.path, "vendor_files": sorted(os.listdir(_vd))[:6] if os.path.isdir(_vd) else None,',
    '          "wb_dir": os.path.isdir(_mod), "wb_pkg": os.path.exists(os.path.join(_mod, "package.xml"))}',
    '    sys.__stderr__.write("PROOF " + json.dumps(_o) + "\\n")',
    'except Exception as e:',
    '    import traceback; sys.__stderr__.write("PROOF FAILED " + traceback.format_exc().replace(chr(10), " | ") + "\\n")',
    'sys.__stderr__.flush()',
  ].join(NL));
  const proof = await waitMarker(p, 'PROOF', 30000);
  console.log('  proof: ' + proof);
  let pr = {};
  try { pr = JSON.parse(proof); } catch (e) {}
  ok(pr.yaml && !proof.startsWith('FAILED'), 'import yaml');
  ok(typeof pr.pkg === 'string' && pr.pkg.indexOf('AdditionalPythonPackages') >= 0, PKG_MOD + ' imported from the vendor dir: ' + pr.pkg);
  ok(pr.vendor_on_path === true, 'vendor dir on sys.path');
  ok(pr.wb_dir === true && pr.wb_pkg === true, 'HistoryWorkbench installed into Mod');

  const log = await p.evaluate(() => (document.getElementById('log') || {}).textContent || '');
  const tail = log.split(NL).filter(l => /fcweb_wheels|Successfully installed|Requirement already|proxy|pypi|wheel/i.test(l)).slice(-8);
  console.log(tail.map(l => '    ' + l).join(NL));
  await b.close();
  console.log(fails ? `${NL}${fails} FAILED` : `${NL}all passed`);
  process.exit(fails ? 1 : 0);
})();
