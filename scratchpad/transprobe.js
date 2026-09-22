// Where does an object's transparency live in the scene graph, and does Coin see it?
//
// Measured so far (issue #5): the transparent box is drawn in the opaque pass with no
// glEnable(GL_BLEND) and no stipple, even though its colour reaches the GL glue with
// alpha 77/255. Coin only blends when SoShape::shouldGLRender finds the TRANSP_MATERIAL
// flag on SoShapeStyleElement and the traversal state's transparency type is a blending
// one (SoShape.cpp:578, SoGLRenderAction.cpp:1274). This asks the scene graph itself,
// through pivy, which of those two is missing:
//   1. does the view provider's SoMaterial carry transparency at all
//   2. what FreeCAD's ShapeAppearance says
//   3. what the same scene looks like to a render action we drive ourselves
//
//   node scratchpad/transprobe.js [url]
const puppeteer = require('puppeteer-core');
const sl = (ms) => new Promise((r) => setTimeout(r, ms));
const NL = String.fromCharCode(10);
const URL = process.argv[2] || 'http://127.0.0.1:8792/freecad-gui.html';
const CHROME = process.env.CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const runPy = (p, c) => p.evaluate((c) => { const m = window.fcInstance; const n = new TextEncoder().encode(c).length + 1; const q = m._malloc(n); m.stringToUTF8(c, q, n); (window.fcRunPy)(m, q); }, c);
const waitFile = async (p, f, ms) => {
  const t = Date.now();
  while (Date.now() - t < ms) {
    const s = await p.evaluate((f) => { try { return window.fcInstance.FS.readFile(f, { encoding: 'utf8' }); } catch (e) { return null; } }, f);
    if (s) return s;
    await sl(1200);
  }
  return null;
};

(async () => {
  const b = await puppeteer.launch({ executablePath: CHROME, headless: true, defaultViewport: { width: 1400, height: 900 },
    args: ['--no-sandbox', '--use-gl=angle'], protocolTimeout: 900000, userDataDir: 'C:/Users/MICHAE~1/AppData/Local/Temp/fc-tp-' + Date.now() });
  const p = (await b.pages())[0];
  await p.goto(URL, { waitUntil: 'domcontentloaded', timeout: 300000 });
  const t = Date.now();
  while (Date.now() - t < 420000) { if (await p.evaluate(() => !!window.__fcWorkReady && !!(window.fcInstance && window.fcInstance._malloc))) break; await sl(1500); }
  await sl(8000);

  await runPy(p, [
    'import FreeCAD as App, FreeCADGui as Gui, json, traceback',
    'o = {}',
    'try:',
    '    d = App.newDocument("TP")',
    '    box = d.addObject("Part::Box", "B"); box.Length = box.Width = box.Height = 20',
    '    d.recompute()',
    '    vo = box.ViewObject',
    '    vo.ShapeColor = (0.1, 0.9, 0.1)',
    '    vo.Transparency = 70',
    '    Gui.updateGui()',
    '    o["transparency_property"] = vo.Transparency',
    '    try:',
    '        app = vo.ShapeAppearance[0]',
    '        o["appearance_transparency"] = app.Transparency',
    '        o["appearance_diffuse"] = str(app.DiffuseColor)',
    '    except Exception as e:',
    '        o["appearance_error"] = repr(e)[:120]',
    '    # every SoMaterial in the scene graph under this view provider root',
    '    from pivy import coin',
    '    def walk(node, depth=0, out=None):',
    '        out = [] if out is None else out',
    '        if depth > 6: return out',
    '        t = str(node.getTypeId().getName().getString())',
    '        if t == "Material":',
    '            m = coin.cast(node, "SoMaterial")',
    '            out.append({"node": str(t),',
    '                        "transparency": [m.transparency[i] for i in range(m.transparency.getNum())],',
    '                        "diffuse_count": m.diffuseColor.getNum()})',
    '        if hasattr(node, "getNumChildren"):',
    '            for i in range(node.getNumChildren()):',
    '                walk(node.getChild(i), depth + 1, out)',
    '        return out',
    '    o["materials"] = walk(vo.RootNode)',
    '    o["packed_alpha_expected"] = int(round(255 * (1 - vo.Transparency / 100.0)))',
    '    # THE question: what transparency type is the viewer render action actually using?',
    '    v = Gui.activeDocument().activeView()',
    '    rm = v.getViewer().getSoRenderManager()',
    '    ga = rm.getGLRenderAction()',
    '    tt = ga.getTransparencyType()',
    '    names = [n for n in dir(coin.SoGLRenderAction) if n.isupper()]',
    '    o["transparency_type"] = int(tt)',
    '    o["type_names"] = {n: int(getattr(coin.SoGLRenderAction, n)) for n in names if isinstance(getattr(coin.SoGLRenderAction, n), int)}',
    '    o["is_sorted_blend"] = (int(tt) == int(coin.SoGLRenderAction.SORTED_OBJECT_SORTED_TRIANGLE_BLEND))',
    '    o["smoothing"] = bool(ga.isSmoothing())',
    '    o["num_passes"] = int(ga.getNumPasses())',
    'except Exception:',
    '    o["exc"] = traceback.format_exc()[-700:]',
    'open("/tmp/tp.json", "w").write(json.dumps(o))',
  ].join(NL));
  const out = await waitFile(p, '/tmp/tp.json', 120000);
  console.log(out);
  if (!out) {
    const log = await p.evaluate(() => ((document.getElementById('log') || {}).textContent || '').split(String.fromCharCode(10)).slice(-25).join(String.fromCharCode(10)));
    console.log('--- page log tail:' + NL + log);
  }
  await b.close();
})();
