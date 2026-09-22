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
    const m = log.match(new RegExp('(' + marker + ') ([^\\n]*)'));
    if (m) return m[2];
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

  // 1. The overlay applies its Addon Manager patches (fcweb_wheels and fcweb_git among
  //    them) as soon as the AM package is importable, which is at boot; it logs one
  //    "[fcweb] addon-manager: ..." note per patch. Wait for ours rather than opening the
  //    GUI: Gui.runCommand('Std_AddonMgr') is exactly the path fcweb_am_boot documents as
  //    aborting the engine when it races the patches.
  const notes = await waitMarker(p, '\\[fcweb\\] addon-manager: pip ->', 90000);
  ok(notes !== null, 'overlay applied the pip patch: ' + notes);
  const gitNote = await waitMarker(p, '\\[fcweb\\] addon-manager: git ->', 30000);
  ok(gitNote !== null, 'overlay applied the git patch: ' + gitNote);
  const dl = await waitMarker(p, '\\[fcweb\\] dulwich', 240000);
  ok(dl !== null && /ready/.test(dl), 'dulwich fetched and importable: ' + dl);

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

  // 3b. Then the add-on itself, as the GUI does after `proceed`: its own AddonInstaller
  //     (the overlay's ZIP pre-fetch path), waiting on finished.
  await runPy(p, [
    'import sys, os, json',
    'try:',
    '    from addonmanager_installer import AddonInstaller',
    '    from Addon import Addon',
    '    _a = Addon("HistoryWorkbench", "https://github.com/eblanshey/HistoryWorkbench", Addon.Status.NOT_INSTALLED, "release")',
    '    _ai = AddonInstaller(_a)',
    '    _r = {}',
    '    def _s(x): _r["success"] = True',
    '    def _f(x, m): _r["failure"] = m',
    '    def _d():',
    '        sys.__stderr__.write("ADDONDONE " + json.dumps(_r) + "\\n"); sys.__stderr__.flush()',
    '    _ai.success.connect(_s); _ai.failure.connect(_f); _ai.finished.connect(_d)',
    '    sys._fcweb_ai = _ai',
    '    _ai.run()',
    'except Exception as e:',
    '    import traceback; sys.__stderr__.write("ADDONDONE FAILED " + traceback.format_exc().replace(chr(10), " | ") + "\\n"); sys.__stderr__.flush()',
  ].join(NL));
  const ad = await waitMarker(p, 'ADDONDONE', 240000);
  console.log('  addon install: ' + ad);
  let adr = {};
  try { adr = JSON.parse(ad); } catch (e) {}
  ok(adr.success === true && !adr.failure, 'HistoryWorkbench AddonInstaller succeeded');

  // 4. Prove it: imports and files.
  await runPy(p, [
    'import sys, os, json, importlib',
    'try:',
    '    importlib.invalidate_caches()',
    '    import yaml',
    '    import ' + PKG_MOD,
    '    import addonmanager_utilities as U',
    '    _vd = U.get_pip_target_directory()',
    '    import addonmanager_freecad_interface as fci',
    '    _mod = os.path.join(fci.DataPaths().mod_dir, "HistoryWorkbench")',
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

  // 5. git, through the History Workbench's own adapter class, against a repo in the
  //    persisted home. Waits for dulwich (fetched as a wheel on first AM activation).
  await runPy(p, [
    'import sys, os, json, importlib, shutil',
    'try:',
    '    importlib.invalidate_caches()',
    '    import dulwich',
    '    import fcweb_git',
    '    import addonmanager_freecad_interface as fci',
    '    mod = os.path.join(fci.DataPaths().mod_dir, "HistoryWorkbench")',
    '    # FreeCAD puts Mod/<addon> on sys.path at the next boot (the "reload to finish" flow);',
    '    # do the same here, and drop any stale namespace-package cache for "freecad".',
    '    if mod not in sys.path: sys.path.insert(0, mod)',
    '    sys.modules.pop("freecad", None); importlib.invalidate_caches()',
    '    from freecad.history_wb.infrastructure.git.git_port_adapter import GitPortAdapter',
    '    class _S:',
    '        def get_git_executable(self): return ""',
    '    ad = GitPortAdapter(_S())',
    '    root = os.path.expanduser("~/gitcheck"); shutil.rmtree(root, ignore_errors=True); os.makedirs(root)',
    '    o = {"which": shutil.which("git"), "available": ad.is_git_executable_available()}',
    '    o["init"] = ad.initialize_repository(root)',
    '    o["top"] = ad.find_top_level_git_path(root)',
    '    open(os.path.join(root, "part.FCStd"), "wb").write(b"PK\\x03\\x04fake")',
    '    o["dirty_before"] = [d.git_path for d in ad.get_dirty_files(root)]',
    '    o["stage"] = ad.stage_files(root, ["part.FCStd"])',
    '    o["staged"] = ad.get_staged_paths(root)',
    '    from freecad.history_wb.domain.git.models import GitIdentity',
    '    o["ident"] = ad.save_identity(root, GitIdentity(name="Web User", email="web@example.com"), False)',
    '    o["commit"] = ad.commit(root, "first from the browser")',
    '    cs = ad.get_commits(root)',
    '    o["commits"] = [(c.message.strip(), c.author) for c in cs]',
    '    o["files_in_head"] = ad.get_committed_files(root, cs[0].id) if cs else None',
    '    o["show"] = ad.get_file_bytes_from_ref(root, cs[0].id, "part.FCStd") == b"PK\\x03\\x04fake" if cs else None',
    '    o["all_fcstd"] = ad.get_all_fcstd_paths(root, None)',
    '    sys.__stderr__.write("GITPROOF " + json.dumps(o) + "\\n")',
    'except Exception as e:',
    '    import traceback; sys.__stderr__.write("GITPROOF FAILED " + traceback.format_exc().replace(chr(10), " | ") + "\\n")',
    'sys.__stderr__.flush()',
  ].join(NL));
  const gp = await waitMarker(p, 'GITPROOF', 120000);
  console.log('  git proof: ' + gp);
  let g = {};
  try { g = JSON.parse(gp); } catch (e) {}
  ok(g.available === true, 'adapter finds git');
  ok(g.init === true && typeof g.top === 'string' && g.top.endsWith('/gitcheck'), 'init + rev-parse --show-toplevel');
  ok(Array.isArray(g.dirty_before) && g.dirty_before.includes('part.FCStd'), 'untracked FCStd reported dirty');
  ok(g.stage === true && Array.isArray(g.staged) && g.staged.includes('part.FCStd'), 'stage + staged paths');
  ok(g.ident === true && g.commit === true, 'identity saved + commit');
  ok(Array.isArray(g.commits) && g.commits.length === 1 && g.commits[0][0] === 'first from the browser' && g.commits[0][1] === 'Web User', 'log parsed: ' + JSON.stringify(g.commits));
  ok(Array.isArray(g.files_in_head) && g.files_in_head.includes('part.FCStd'), 'diff-tree lists the file');
  ok(g.show === true, 'show returns the committed bytes');

  const log = await p.evaluate(() => (document.getElementById('log') || {}).textContent || '');
  const tail = log.split(NL).filter(l => /fcweb_wheels|Successfully installed|Requirement already|proxy|pypi|wheel/i.test(l)).slice(-8);
  console.log(tail.map(l => '    ' + l).join(NL));
  await b.close();
  console.log(fails ? `${NL}${fails} FAILED` : `${NL}all passed`);
  process.exit(fails ? 1 : 0);
})();
