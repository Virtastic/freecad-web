// Why is the shading flat and transparency missing? (kwahoo2, 2026-09-22)
//
// Two questions, answered at the only place that cannot lie: the WebGL calls the page
// actually makes, and the shader emscripten's GL emulation actually compiles.
//
//   lighting     Coin drives the fixed-function pipeline: glEnable(GL_LIGHTING),
//                glLightfv, glMaterialfv, glNormal3f. tools/patch-freecad-js.py already
//                counts the calls that fall through to a no-op in the emulation
//                (globalThis.__fcglNoop). If lighting is "off", either those counters
//                are climbing or the generated fragment shader has no lighting terms.
//   transparency FreeCAD asks Coin for SORTED_OBJECT_SORTED_TRIANGLE_BLEND
//                (View3DInventorViewer.cpp:679), which is real alpha blending, so a
//                transparent object must produce enable(GL_BLEND) plus a blendFunc and
//                a draw with alpha < 1. If none of that reaches the context, the object
//                renders opaque.
//
// The context is wrapped before the engine boots, so nothing is missed, and the scene is
// built through FreeCAD's own API: one opaque box, one 70% transparent box in front of it.
//
//   node scratchpad/gldiag.js [url]
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
    args: ['--no-sandbox', '--use-gl=angle'], protocolTimeout: 900000, userDataDir: 'C:/Users/MICHAE~1/AppData/Local/Temp/fc-gl-' + Date.now() });
  const p = (await b.pages())[0];

  // Wrap every WebGL context the page creates, before the engine exists.
  await p.evaluateOnNewDocument(() => {
    window.__gl = { enables: {}, disables: {}, blendFunc: [], shaders: [], draws: 0, contexts: 0, colors: [] };
    const orig = HTMLCanvasElement.prototype.getContext;
    HTMLCanvasElement.prototype.getContext = function (type, attrs) {
      const ctx = orig.call(this, type, attrs);
      if (!ctx || !/webgl/.test(type) || ctx.__wrapped) return ctx;
      ctx.__wrapped = true;
      window.__gl.contexts++;
      const name = (c) => ({ 3042: 'BLEND', 2929: 'DEPTH_TEST', 2884: 'CULL_FACE', 2848: 'LINE_SMOOTH',
                             32823: 'POLYGON_OFFSET_FILL', 2832: 'POLYGON_OFFSET_POINT' })[c] || String(c);
      const wrap = (fn, cb) => { const o = ctx[fn].bind(ctx); ctx[fn] = function (...a) { try { cb(a); } catch (e) {} return o(...a); }; };
      wrap('enable', (a) => { const n = name(a[0]); window.__gl.enables[n] = (window.__gl.enables[n] || 0) + 1; });
      wrap('disable', (a) => { const n = name(a[0]); window.__gl.disables[n] = (window.__gl.disables[n] || 0) + 1; });
      wrap('blendFunc', (a) => { if (window.__gl.blendFunc.length < 4) window.__gl.blendFunc.push(a.join(',')); });
      wrap('shaderSource', (a) => { if (window.__gl.shaders.length < 8) window.__gl.shaders.push(String(a[1])); });
      wrap('drawElements', () => { window.__gl.draws++; });
      wrap('drawArrays', () => { window.__gl.draws++; });
      wrap('vertexAttrib4f', (a) => { if (window.__gl.colors.length < 6) window.__gl.colors.push(a.slice(1).join(',')); });
      return ctx;
    };
  });

  await p.goto(URL, { waitUntil: 'domcontentloaded', timeout: 300000 });
  const t = Date.now();
  while (Date.now() - t < 420000) { if (await p.evaluate(() => !!window.__fcWorkReady && !!(window.fcInstance && window.fcInstance._malloc))) break; await sl(1500); }
  await sl(8000);

  // A scene that MUST blend: a red box, and a 70% transparent green box in front of it.
  await runPy(p, [
    'import FreeCAD as App, FreeCADGui as Gui, json',
    'd = App.newDocument("GL")',
    'back = d.addObject("Part::Box", "Back"); back.Length = 40; back.Width = 40; back.Height = 40',
    'front = d.addObject("Part::Box", "Front"); front.Length = 60; front.Width = 5; front.Height = 60',
    'front.Placement.Base = App.Vector(-10, -20, -10)',
    'd.recompute()',
    'back.ViewObject.ShapeColor = (0.9, 0.1, 0.1)',
    'front.ViewObject.ShapeColor = (0.1, 0.9, 0.1)',
    'front.ViewObject.Transparency = 70',
    'Gui.activeDocument().activeView().viewAxonometric(); Gui.SendMsgToActiveView("ViewFit")',
    'Gui.updateGui()',
    'open("/tmp/gl-scene.json", "w").write(json.dumps({"transparency": front.ViewObject.Transparency, "objs": len(d.Objects)}))',
  ].join(NL));
  console.log('  scene: ' + await waitFile(p, '/tmp/gl-scene.json', 60000));
  await sl(6000);
  // force a few redraws so the transparent pass definitely runs
  await runPy(p, [
    'import FreeCADGui as Gui',
    'v = Gui.activeDocument().activeView()',
    'for _ in range(6):',
    '    v.viewAxonometric(); Gui.updateGui()',
  ].join(NL));
  await sl(6000);

  // The counters that matter: these live INSIDE the engine's GL glue
  // (scratchpad/glinstrument.js), so they see Coin's calls, not Qt's compositor.
  const glue = await p.evaluate(() => ({ count: globalThis.__fcglCount || null, args: globalThis.__fcglArgs || null, noop: globalThis.__fcglNoop || null }));
  const interesting = {};
  for (const k in (glue.count || {})) {
    if (/blendFunc|normalPointer|enable_3042|disable_3042|enable_2896|disable_2896|clientState_on_|lightfv_pname_|materialfv_pname_/.test(k)) interesting[k] = glue.count[k];
  }
  console.log('  GLUE counters: ' + JSON.stringify(interesting));
  console.log('  ALL glue keys: ' + JSON.stringify(Object.keys(glue.count || {}).sort()));
  const emu = await p.evaluate(() => {
    const E = globalThis.__fcGLE, I = globalThis.__fcGLI;
    if (!E || !I) return null;
    return { colorMaterial: E.__fcColorMaterial, lightEnabled: E.lightEnabled,
             materialDiffuse: Array.from(E.materialDiffuse || []), materialAmbient: Array.from(E.materialAmbient || []),
             clientAttribs: Array.from(I.enabledClientAttributes || []),
             clientColor: Array.from(I.clientColor || []),
             colorAttrib: I.clientAttributes && I.clientAttributes[2] ? { size: I.clientAttributes[2].size, type: I.clientAttributes[2].type, enabled: I.clientAttributes[2].enabled } : null };
  });
  console.log('  EMULATION state: ' + JSON.stringify(emu));
  // The state the emulation used when it BUILT its fixed-function shader, and the shader.
  const gen = await p.evaluate(() => {
    const g = globalThis.__fcShaderGen || [], src = globalThis.__fcShaderSrc || [];
    const lit = src.filter(s => /u_lightDiffuse|diffuseI/.test(s));
    return { generations: g.length, states: g.slice(0, 6), compiled: src.length,
             withLighting: lit.length, sample: (lit[0] || src.find(s => /a_color/.test(s)) || src[0] || '').slice(0, 700) };
  });
  const emuEn = await p.evaluate(() => ({ enable: globalThis.__fcEmuEnable || null, disable: globalThis.__fcEmuDisable || null }));
  const nm = (c) => ({ 2896: 'GL_LIGHTING', 16384: 'GL_LIGHT0', 16385: 'GL_LIGHT1', 2903: 'GL_COLOR_MATERIAL', 3042: 'GL_BLEND', 2929: 'GL_DEPTH_TEST', 2884: 'GL_CULL_FACE', 3553: 'GL_TEXTURE_2D', 2912: 'GL_FOG', 32823: 'GL_POLYGON_OFFSET_FILL', 3089: 'GL_SCISSOR_TEST', 2848: 'GL_LINE_SMOOTH', 2832: 'GL_POINT_SMOOTH', 2960: 'GL_STENCIL_TEST', 3024: 'GL_DITHER', 32925: 'GL_SAMPLE_ALPHA_TO_COVERAGE', 32926: 'GL_SAMPLE_ALPHA_TO_ONE', 32928: 'GL_SAMPLE_COVERAGE', 3008: 'GL_ALPHA_TEST' }[c] || c);
  const pretty = (o) => JSON.stringify(Object.fromEntries(Object.entries(o || {}).map(([k, v]) => [nm(+k), v])));
  console.log('  EMULATION enable():  ' + pretty(emuEn.enable));
  console.log('  EMULATION disable(): ' + pretty(emuEn.disable));
  // The tail of the ordered trace: what happens around the last draws of the frame, which
  // is where the sorted transparent pass runs.
  // The window around Coin's own geometry draws (glDrawElements), which is where the
  // sorted transparent pass lives. The tail of the trace is Qt's compositor.
  const trace = await p.evaluate(() => {
    const t = globalThis.__fcglTrace || [];
    const idx = t.map((x, i) => [x, i]).filter(([x]) => /DrawElements/.test(x)).map(([, i]) => i);
    if (!idx.length) return { draws: 0, window: [] };
    const first = idx[Math.max(0, idx.length - 3)];
    return { draws: idx.length, window: t.slice(Math.max(0, first - 30), first + 12) };
  });
  console.log('  TRACE around the last geometry draws (' + trace.draws + ' drawElements total):' + NL +
    trace.window.map(x => '    ' + x).join(NL));
  console.log('  SHADER generations: ' + gen.generations + ', compiled: ' + gen.compiled + ', with a lighting pass: ' + gen.withLighting);
  console.log('  SHADER gen state: ' + JSON.stringify(gen.states));
  console.log('  SHADER sample:' + NL + gen.sample);
  console.log('  GLUE blendFunc args: ' + JSON.stringify((glue.args || {}).blendFunc));
  console.log('  GLUE no-ops: ' + JSON.stringify(glue.noop));
  const table = await p.evaluate(() => {
    const all = globalThis.__fcglAll || {}, seen = globalThis.__fcglSeen || {};
    const pick = {};
    for (const k in all) if (/Color|Material|Light|Blend|Enable$|EnableClientState|Normal|Interleaved|Draw/.test(k)) pick[k] = all[k];
    return { pick, seen, total: Object.keys(all).length };
  });
  console.log('  IMPORT TABLE (' + table.total + ' gl entries): ' + JSON.stringify(table.pick));
  console.log('  colour/material arguments: ' + JSON.stringify(table.seen).slice(0, 900));

  // Lighting: does the bright face follow the camera, as a headlight must?
  for (const [name, cmd] of [['axo', 'viewAxonometric'], ['front', 'viewFront'], ['top', 'viewTop'], ['rear', 'viewRear']]) {
    await runPy(p, ['import FreeCADGui as Gui',
                    'v = Gui.activeDocument().activeView()',
                    'v.' + cmd + '(); Gui.SendMsgToActiveView("ViewFit"); Gui.updateGui()'].join(NL));
    await sl(3500);
    await p.screenshot({ path: 'C:/tmp/gldiag-' + name + '.png' });
  }
  console.log('  screenshots: C:/tmp/gldiag-{axo,front,top,rear}.png');

  const gl = await p.evaluate(() => {
    const g = window.__gl;
    const frag = (g.shaders.find(s => /gl_FragColor|out vec4/.test(s)) || '');
    const vert = (g.shaders.find(s => /gl_Position/.test(s)) || '');
    return {
      contexts: g.contexts, draws: g.draws, enables: g.enables, disables: g.disables,
      blendFunc: g.blendFunc, colors: g.colors,
      shaderCount: g.shaders.length,
      fragHasLighting: /light|Light|normal|Normal/.test(frag),
      vertHasLighting: /light|Light|u_normalMatrix|a_normal/.test(vert),
      vertSample: vert.slice(0, 420),
      fragSample: frag.slice(0, 420),
      noop: globalThis.__fcglNoop || null,
    };
  });
  console.log('  contexts=' + gl.contexts + ' draws=' + gl.draws + ' shaders=' + gl.shaderCount);
  console.log('  enable():  ' + JSON.stringify(gl.enables));
  console.log('  disable(): ' + JSON.stringify(gl.disables));
  console.log('  blendFunc: ' + JSON.stringify(gl.blendFunc));
  console.log('  per-vertex colours seen: ' + JSON.stringify(gl.colors));
  console.log('  emulation no-op counters (from tools/patch-freecad-js.py): ' + JSON.stringify(gl.noop));
  console.log('  vertex shader mentions lighting: ' + gl.vertHasLighting);
  console.log('  fragment shader mentions lighting: ' + gl.fragHasLighting);
  console.log('  --- vertex shader ---' + NL + gl.vertSample);
  console.log('  --- fragment shader ---' + NL + gl.fragSample);

  await p.screenshot({ path: 'C:/tmp/gldiag.png' });
  console.log('  screenshot: C:/tmp/gldiag.png');
  await b.close();
})();
