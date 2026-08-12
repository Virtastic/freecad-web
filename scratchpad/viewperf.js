// In-app view performance: real mouse-drag orbit on three model weights, measuring true
// frame rate AND the GL work behind each frame. Frames are counted at the COLOR_BUFFER
// clear (a real frame start); per-frame GL counts say WHY a frame costs what it costs.
const puppeteer = require('puppeteer-core');
const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const sl = (ms) => new Promise((r) => setTimeout(r, ms));

const MODELS = [
  ['PartDesign', '/freecad/share/examples/PartDesignExample.FCStd'],
  ['EngineBlock', '/freecad/share/examples/EngineBlock.FCStd'],
  ['BIM', '/freecad/share/examples/BIMExample.FCStd'],
];

const run = (p, c) => p.evaluate((c) => {
  const m = window.fcInstance;
  const n = new TextEncoder().encode(c).length + 1;
  const q = m._malloc(n); m.stringToUTF8(c, q, n);
  (window.fcRunPy || ((mm, pp) => { mm._fcweb_run_python(pp); mm._free(pp); }))(m, q);
}, c);

const waitFor = async (p, mark, ms) => {
  const t0 = Date.now();
  while (Date.now() - t0 < ms) {
    const t = await p.evaluate(() => (document.getElementById('log') || {}).textContent || '');
    if (t.includes(mark)) return true;
    await sl(500);
  }
  return false;
};

(async () => {
  const b = await puppeteer.launch({ executablePath: CHROME, headless: false, defaultViewport: null,
    args: ['--no-sandbox', '--use-gl=angle', '--use-angle=metal', '--window-size=1400,900'],
    protocolTimeout: 2400000, userDataDir: '/tmp/fc-viewperf' });
  const p = (await b.pages())[0];
  await p.goto('http://localhost:8791/index.html', { waitUntil: 'domcontentloaded', timeout: 300000 });
  const t0 = Date.now();
  while (Date.now() - t0 < 300000) { if (await p.evaluate(() => !!(window.fcInstance && window.fcInstance._malloc))) break; await sl(1000); }
  await sl(9000);

  // Instrument the GL context once: frame boundaries + the calls that dominate an
  // immediate-mode renderer.
  await p.evaluate(() => {
    window.__gl = { frames: [], n: {} };
    const P = WebGL2RenderingContext.prototype;
    const bump = (k, by) => { window.__gl.n[k] = (window.__gl.n[k] || 0) + (by || 1); };
    const wrap = (name, extra) => {
      const orig = P[name];
      if (!orig) return;
      P[name] = function () { bump(name); if (extra) extra.apply(this, arguments); return orig.apply(this, arguments); };
    };
    const clear = P.clear;
    P.clear = function (m) {
      if (m & this.COLOR_BUFFER_BIT) { window.__gl.frames.push(performance.now()); }
      return clear.apply(this, arguments);
    };
    ['drawArrays', 'drawElements', 'useProgram', 'bindBuffer', 'uniformMatrix4fv',
     'uniform4fv', 'vertexAttribPointer', 'enableVertexAttribArray', 'getParameter',
     'isProgram', 'bindTexture', 'readPixels'].forEach((f) => wrap(f));
    const bd = P.bufferData;
    P.bufferData = function (t, d) {
      bump('bufferData');
      bump('bufferBytes', (d && (d.byteLength || d.length || 0)) || 0);
      return bd.apply(this, arguments);
    };
  });

  const results = [];
  for (const [name, path] of MODELS) {
    await run(p, [
      'import sys, FreeCAD as App, FreeCADGui as Gui',
      'd=App.openDocument("' + path + '")',
      'Gui.updateGui()',
      'av=Gui.ActiveDocument.ActiveView',
      'av.viewAxonometric(); av.fitAll(); Gui.updateGui()',
      'sys.__stderr__.write("VP-OPEN ' + name + '\\n"); sys.__stderr__.flush()',
    ].join('\n'));
    if (!await waitFor(p, 'VP-OPEN ' + name, 600000)) { results.push([name, 'open timed out']); continue; }
    await sl(3000);

    // real mouse drag across the viewport (middle of the window)
    await p.evaluate(() => { window.__gl.frames = []; window.__gl.n = {}; });
    await p.mouse.move(700, 450);
    await p.mouse.down({ button: 'left' });
    const tStart = Date.now();
    for (let i = 0; i < 60; i++) {
      await p.mouse.move(700 + Math.round(150 * Math.sin(i / 7)), 450 + Math.round(100 * Math.cos(i / 6)));
    }
    await p.mouse.up({ button: 'left' });
    const wall = Date.now() - tStart;
    const g = await p.evaluate(() => ({ frames: window.__gl.frames.length, n: window.__gl.n }));
    const fps = g.frames / (wall / 1000);
    const per = (k) => (g.frames ? Math.round((g.n[k] || 0) / g.frames) : 0);
    results.push([name, {
      fps: +fps.toFixed(1), frames: g.frames, wallMs: wall,
      msPerFrame: +(wall / Math.max(1, g.frames)).toFixed(1),
      drawsPerFrame: per('drawArrays') + per('drawElements'),
      bufferDataPerFrame: per('bufferData'),
      kbUploadedPerFrame: +(((g.n.bufferBytes || 0) / Math.max(1, g.frames)) / 1024).toFixed(1),
      useProgramPerFrame: per('useProgram'),
      bindBufferPerFrame: per('bindBuffer'),
      getParameterPerFrame: per('getParameter'),
      isProgramPerFrame: per('isProgram'),
      vertexAttribPointerPerFrame: per('vertexAttribPointer'),
    }]);
    await run(p, 'App.closeDocument(App.ActiveDocument.Name)');
    await sl(2000);
  }
  console.log(JSON.stringify(results, null, 1));
  await b.close().catch(() => {});
  process.exit(0);
})().catch((e) => { console.log('DRIVER ' + e); process.exit(1); });
