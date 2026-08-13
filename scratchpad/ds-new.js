// Would a real user lose work? Four scenarios, each ending in a genuine page reload with
// the same browser profile, asserting the GEOMETRY is back (not merely that a document
// opened). The distinction that matters: writing a file into the emscripten FS is not
// the same as it reaching IndexedDB.
const puppeteer = require('puppeteer-core');
const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const sl = (ms) => new Promise((r) => setTimeout(r, ms));
const PROFILE = '/tmp/fc-datasafety-' + (process.argv[3] || 'a');
const run = (p, c) => p.evaluate((c) => { const m = window.fcInstance;
  const n = new TextEncoder().encode(c).length + 1; const q = m._malloc(n); m.stringToUTF8(c, q, n);
  (window.fcRunPy || ((mm, pp) => { mm._fcweb_run_python(pp); mm._free(pp); }))(m, q); }, c);
const pw = async (p, mk, ms) => { const t0 = Date.now();
  while (Date.now() - t0 < ms) { try { if (await p.evaluate((k) =>
    document.getElementById('log').textContent.includes(k), mk)) return true; } catch (e) {} await sl(400); } return false; };
const tail = async (p, re) => { const t = await p.evaluate(() => document.getElementById('log').textContent);
  const m = t.match(re) || []; return m[m.length - 1] || '(none)'; };

async function boot(p) {
  await p.goto('http://localhost:8793/index.html', { waitUntil: 'domcontentloaded', timeout: 300000 });
  const t0 = Date.now();
  while (Date.now() - t0 < 300000) { if (await p.evaluate(() => !!(window.fcInstance && window.fcInstance._malloc))) break; await sl(1000); }
  await sl(16000);   // boot settles; the restore pass runs at ~13s
}
// a box of a distinctive size, so "the work came back" is checkable by volume
const MAKE = (n, L) => ['import FreeCAD as App, sys',
  'd=App.newDocument("' + n + '")',
  'b=d.addObject("Part::Box","B"); b.Length=' + L + '; b.Width=20; b.Height=10',
  'd.recompute()',
  'sys.__stderr__.write("MADE %s vol=%.1f\\n" % (d.Name, b.Shape.Volume)); sys.__stderr__.flush()'].join('\n');
const CHECK = ['import FreeCAD as App, sys',
  'tot=0.0; names=[]',
  'for d in App.listDocuments().values():',
  '    for o in d.Objects:',
  '        try: tot+=o.Shape.Volume',
  '        except Exception: pass',
  '    names.append(d.Name)',
  'sys.__stderr__.write("CHECK docs=%s vol=%.1f\\n" % (",".join(sorted(names)) or "-", tot)); sys.__stderr__.flush()'].join('\n');

(async () => {
  const b = await puppeteer.launch({ executablePath: CHROME, headless: false, defaultViewport: null,
    args: ['--no-sandbox', '--use-gl=angle', '--use-angle=metal', '--window-size=1300,850'],
    protocolTimeout: 2400000, userDataDir: PROFILE });
  const p = (await b.pages())[0];
  const scenario = process.argv[2] || 'all';
  const results = [];

  if (scenario === 'all' || scenario === 'autosave') {
    await boot(p);
    await run(p, MAKE('AutoSaveDoc', 100));     // 100*20*10 = 20000
    await pw(p, 'MADE', 60000);
    await sl(40000);                            // let the 30 s autosave tick fire
    await boot(p);                              // real reload
    await run(p, CHECK); await pw(p, 'CHECK', 60000);
    results.push('after 30s autosave + reload: ' + await tail(p, /CHECK [^\n]*/g) + '  (want vol=20000)');
  }

  if (scenario === 'all' || scenario === 'fast') {
    await p.evaluate(() => indexedDB.deleteDatabase('/home/web_user')).catch(() => {});
    await boot(p);
    await run(p, MAKE('FastDoc', 50));          // 50*20*10 = 10000
    await pw(p, 'MADE', 60000);
    await sl(3000);                             // user reloads almost immediately
    await boot(p);
    await run(p, CHECK); await pw(p, 'CHECK', 60000);
    results.push('reload 3s after modelling:    ' + await tail(p, /CHECK [^\n]*/g) + '  (want vol=10000)');
  }

  if (scenario === 'all' || scenario === 'explicit') {
    await boot(p);
    await run(p, ['import FreeCAD as App, sys',
      'd=App.newDocument("SavedDoc")',
      'b=d.addObject("Part::Box","B"); b.Length=30; b.Width=20; b.Height=10',
      'd.recompute()',
      'd.saveAs("/home/web_user/SavedDoc.FCStd")',
      'sys.__stderr__.write("SAVED\\n"); sys.__stderr__.flush()'].join('\n'));
    await pw(p, 'SAVED', 120000);
    await sl(4000);
    await boot(p);
    await run(p, ['import FreeCAD as App, os, sys',
      'e=os.path.exists("/home/web_user/SavedDoc.FCStd")',
      'v=-1.0',
      'if e:',
      '    d=App.openDocument("/home/web_user/SavedDoc.FCStd")',
      '    v=sum(o.Shape.Volume for o in d.Objects if hasattr(o,"Shape"))',
      'sys.__stderr__.write("EXPLICIT exists=%s vol=%.1f\\n" % (e, v)); sys.__stderr__.flush()'].join('\n'));
    await pw(p, 'EXPLICIT', 120000);
    results.push('explicit save + reload:       ' + await tail(p, /EXPLICIT [^\n]*/g) + '  (want exists=True vol=6000)');
  }

  console.log(results.join('\n'));
  await b.close().catch(() => {}); process.exit(0);
})().catch((e) => { console.log('DRIVER ' + String(e).slice(0, 250)); process.exit(1); });
