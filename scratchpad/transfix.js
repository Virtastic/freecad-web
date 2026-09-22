// Which half of Coin's transparency decision is failing?
//
// SoShape::shouldGLRender asks SoGLRenderAction::handleTransparency(transparent), and
// that returns immediately, with blending OFF, when the shape is not flagged transparent
// or the type is NONE / SCREEN_DOOR (Coin, SoGLRenderAction.cpp:1274). Measured already:
// the viewer's type IS SORTED_OBJECT_SORTED_TRIANGLE_BLEND (8), the material carries 0.7
// transparency, and the colour reaches GL with alpha 77. Yet the box draws opaque with no
// blend enable.
//
// So either the shape is not flagged transparent, or the sorted pass that would blend it
// never runs. Switching the action to plain BLEND separates the two: with BLEND, a shape
// that IS flagged transparent gets blending switched on inline, no second pass involved.
//
//   transparent under BLEND  -> the flag is fine, the sorted/delayed pass is broken
//   still opaque under BLEND -> the shape is never flagged transparent
//
//   node scratchpad/transfix.js [url]
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
// The WebGL canvas is created without preserveDrawingBuffer, so reading it back from the
// page gives an undrawn (black) frame. The screenshots are the evidence instead.
const SCENE = [
  'import FreeCAD as App, FreeCADGui as Gui',
  'd = App.newDocument("TX")',
  'back = d.addObject("Part::Box", "Back"); back.Length = 40; back.Width = 40; back.Height = 40',
  'front = d.addObject("Part::Box", "Front"); front.Length = 60; front.Width = 5; front.Height = 60',
  'front.Placement.Base = App.Vector(-10, -20, -10)',
  'd.recompute()',
  'back.ViewObject.ShapeColor = (0.9, 0.1, 0.1)',
  'front.ViewObject.ShapeColor = (0.1, 0.9, 0.1)',
  'front.ViewObject.Transparency = 70',
  'v = Gui.activeDocument().activeView()',
  'v.viewAxonometric(); Gui.SendMsgToActiveView("ViewFit"); Gui.updateGui()',
].join(NL);

const SETTYPE = (t) => [
  'import FreeCADGui as Gui, json',
  'from pivy import coin',
  'v = Gui.activeDocument().activeView()',
  'ga = v.getViewer().getSoRenderManager().getGLRenderAction()',
  'ga.setTransparencyType(' + t + ')',
  'v.getViewer().getSoRenderManager().scheduleRedraw()',
  'Gui.updateGui()',
  'open("/tmp/tx.json", "w").write(json.dumps({"type": int(ga.getTransparencyType())}))',
].join(NL);

(async () => {
  const b = await puppeteer.launch({ executablePath: CHROME, headless: true, defaultViewport: { width: 1400, height: 900 },
    args: ['--no-sandbox', '--use-gl=angle'], protocolTimeout: 900000, userDataDir: 'C:/Users/MICHAE~1/AppData/Local/Temp/fc-tx-' + Date.now() });
  const p = (await b.pages())[0];
  await p.goto(URL, { waitUntil: 'domcontentloaded', timeout: 300000 });
  const t0 = Date.now();
  while (Date.now() - t0 < 420000) { if (await p.evaluate(() => !!window.__fcWorkReady && !!(window.fcInstance && window.fcInstance._malloc))) break; await sl(1500); }
  await sl(8000);
  await runPy(p, SCENE);
  await sl(9000);

  // Where the green box covers the red one. If transparency works, red bleeds through.
  await p.screenshot({ path: 'C:/tmp/transfix-before.png' });
  console.log('  sorted blend (8), as shipped -> C:/tmp/transfix-before.png');

  // Is FreeCAD drawing its shapes through the VBO path? That path in SoBrepFaceSet is a
  // different renderer from the one that consults shouldGLRender.
  await runPy(p, require('fs').readFileSync('C:/tmp/vboprobe.txt', 'utf8'));
  console.log('  VBO state: ' + await waitFile(p, '/tmp/vbo.json', 60000));

  // A transparent cube built straight from pivy, bypassing FreeCAD's view provider and
  // SoBrepFaceSet entirely. If THIS blends and the Part::Box does not, the difference is
  // in FreeCAD's node graph rather than in Coin or our GL glue.
  await runPy(p, require('fs').readFileSync('C:/tmp/pivyscene.txt', 'utf8'));
  console.log('  pivy scene: ' + await waitFile(p, '/tmp/pivy.json', 60000));
  await sl(7000);
  await p.screenshot({ path: 'C:/tmp/transfix-pivy.png' });
  console.log('  hand-built pivy cube (still sorted blend) -> C:/tmp/transfix-pivy.png');

  // VBO off: does FreeCAD's own geometry become transparent?
  await runPy(p, require('fs').readFileSync('C:/tmp/vbooff.txt', 'utf8'));
  console.log('  VBO off: ' + await waitFile(p, '/tmp/vbooff.json', 60000));
  await sl(8000);
  await p.screenshot({ path: 'C:/tmp/transfix-novbo.png' });
  console.log('  with UseVBO false -> C:/tmp/transfix-novbo.png');

  // Objects CREATED with VBO off, so their nodes are built on the other path.
  await runPy(p, require('fs').readFileSync('C:/tmp/vbonew.txt', 'utf8'));
  console.log('  fresh doc, VBO off: ' + await waitFile(p, '/tmp/vbonew.json', 60000));
  await sl(9000);
  await p.screenshot({ path: 'C:/tmp/transfix-novbo-fresh.png' });
  console.log('  fresh objects with UseVBO false -> C:/tmp/transfix-novbo-fresh.png');

  // Which material node sits in the branch the switch actually renders?
  await runPy(p, require('fs').readFileSync('C:/tmp/matwalk.txt', 'utf8'));
  console.log('  node walk: ' + (await waitFile(p, '/tmp/matwalk.json', 60000) || '').slice(0, 1500));

  // Force transparency onto EVERY material under the view provider, in case FreeCAD sets
  // a node that is not the one being rendered.
  await runPy(p, require('fs').readFileSync('C:/tmp/matset.txt', 'utf8'));
  console.log('  forced materials: ' + await waitFile(p, '/tmp/matset.json', 60000));
  await sl(8000);
  await p.screenshot({ path: 'C:/tmp/transfix-forced.png' });
  console.log('  every material forced to 0.7 -> C:/tmp/transfix-forced.png');

  // Flat Lines draws faces and edges together; Shaded is the plain face branch.
  await runPy(p, require('fs').readFileSync('C:/tmp/dispmode.txt', 'utf8'));
  console.log('  display mode: ' + await waitFile(p, '/tmp/disp.json', 60000));
  await sl(8000);
  await p.screenshot({ path: 'C:/tmp/transfix-shaded.png' });
  console.log('  Shaded display mode -> C:/tmp/transfix-shaded.png');

  // A pivy cube INSIDE FreeCAD's own view provider root: same state context as the
  // SoBrepFaceSet that will not blend. Transparent here means the node is at fault;
  // opaque here means the state around it is.
  await runPy(p, require('fs').readFileSync('C:/tmp/inside.txt', 'utf8'));
  console.log('  cube inside the view provider: ' + await waitFile(p, '/tmp/inside.json', 60000));
  await sl(8000);
  await p.screenshot({ path: 'C:/tmp/transfix-inside.png' });
  console.log('  -> C:/tmp/transfix-inside.png');

  for (const [name, t] of [['BLEND', 'coin.SoGLRenderAction.BLEND'],
                           ['DELAYED_BLEND', 'coin.SoGLRenderAction.DELAYED_BLEND'],
                           ['SORTED_OBJECT_BLEND', 'coin.SoGLRenderAction.SORTED_OBJECT_BLEND']]) {
    await runPy(p, SETTYPE(t));
    const st = await waitFile(p, '/tmp/tx.json', 60000);
    await sl(6000);
    await p.screenshot({ path: 'C:/tmp/transfix-' + name + '.png' });
    console.log('  ' + name.padEnd(20) + ' ' + st + ' -> C:/tmp/transfix-' + name + '.png');
    await runPy(p, 'import os\ntry: os.remove("/tmp/tx.json")\nexcept Exception: pass');
  }
  await b.close();
})();
