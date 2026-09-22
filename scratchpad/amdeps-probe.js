// Addon Manager Python-dependency probe. Before touching the pip path, measure what the
// SHIPPED engine has: where the vendor dir resolves, whether it is inside the persisted
// home, what sys.path holds, and whether zipfile + our proxy fetch can reach PyPI.
//   node scratchpad/amdeps-probe.js https://freecad.virtastic.app/
const puppeteer = require('puppeteer-core');
const sl = (ms) => new Promise((r) => setTimeout(r, ms));
const NL = String.fromCharCode(10);
const BS = String.fromCharCode(92);
const URL = process.argv[2] || 'https://freecad.virtastic.app/';
const CHROME = process.env.CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe';

const runPy = (p, c) => p.evaluate((c) => {
  const m = window.fcInstance;
  const n = new TextEncoder().encode(c).length + 1;
  const q = m._malloc(n);
  m.stringToUTF8(c, q, n);
  (window.fcRunPy || ((mm, pp) => { mm._fcweb_run_python(pp); mm._free(pp); }))(m, q);
}, c);

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
  await runPy(p, [
    'import sys, os, json',
    'try:',
    '    sys.path.append("/freecad/Mod/AddonManager")',
    '    import addonmanager_utilities as U',
    '    import addonmanager_freecad_interface as fci',
    '    vd = U.get_pip_target_directory()',
    '    call = "n/a (create_pip_call raises: no python exe)"',
    '    home = os.path.expanduser("~")',
    '    mod_dir = fci.DataPaths().mod_dir',
    '    import shutil',
    '    _o = {"vendor": vd, "vendor_exists": os.path.isdir(vd), "in_home": vd.startswith(home), "home": home,',
    '          "mod_dir": mod_dir, "pip_call": call, "syspath_has_vendor": vd in sys.path,',
    '          "has_pip": bool(__import__("importlib").util.find_spec("pip")), "has_zipfile": bool(__import__("importlib").util.find_spec("zipfile")),',
    '          "has_yaml": bool(__import__("importlib").util.find_spec("yaml")), "platform": sys.platform, "pyver": sys.version.split()[0],',
    '          "proxy_hosts": sorted(getattr(__import__("NetworkManager"), "FCWEB_PROXY_HOSTS", {}).keys()) if __import__("importlib").util.find_spec("NetworkManager") else None,',
    '          "syspath": [x for x in sys.path if "Additional" in x or "site-packages" in x]}',
    '    _out = json.dumps(_o)',
    'except Exception as e:',
    '    import traceback; _out = "FAILED " + traceback.format_exc().replace(chr(10), " | ")',
    'sys.__stderr__.write("PROBEOUT " + _out + "' + BS + 'n")',
    'sys.__stderr__.flush()',
  ].join(NL));
  let done = false;
  for (let i = 0; i < 60 && !done; i += 1) {
    const log = await p.evaluate(() => (document.getElementById('log') || {}).textContent || '');
    const hits = log.match(/PROBEOUT [^\n]*/g);
    if (hits) { console.log(hits.join(NL)); done = true; break; }
    await sl(2000);
  }
  if (!done) console.log('no PROBEOUT within 120 s');
  await b.close();
})();
