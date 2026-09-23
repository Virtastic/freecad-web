// Count what the engine's GL glue really does, without a relink.
//
// Page-level tracing lies here: Qt's compositor and Coin's renderer use different WebGL
// contexts, and wrapping getContext from the page caught the compositor (measured
// 2026-09-22, which is why the first transparency reading was thrown away). The glue
// inside FreeCAD.js is where Coin's calls actually land, so the counters go there, the
// same way tools/patch-freecad-js.py already counts the no-op fixed-function calls.
//
// Writes an instrumented copy of FreeCAD.js; scratchpad/testserver.js serves it in place
// of the shipped file when FCJS_OVERRIDE points at it. Counters land on
// globalThis.__fcglCount, with the first few argument sets on __fcglArgs.
//
//   node scratchpad/glinstrument.js <in FreeCAD.js> <out FreeCAD.js>
const fs = require('fs');
const IN = process.argv[2] || 'C:/tmp/prod-fc.js';
const OUT = process.argv[3] || 'C:/tmp/fc-instrumented.js';

// counter with a fixed key
const HIT = (k) => `(globalThis.__fcglCount=globalThis.__fcglCount||{},globalThis.__fcglCount[${JSON.stringify(k)}]=(globalThis.__fcglCount[${JSON.stringify(k)}]||0)+1)`;
// counter whose key is built from an argument, e.g. enable_3042
const HITV = (prefix, expr) => `(globalThis.__fcglCount=globalThis.__fcglCount||{},globalThis.__fcglCount[${JSON.stringify(prefix)}+${expr}]=(globalThis.__fcglCount[${JSON.stringify(prefix)}+${expr}]||0)+1)`;
// remember the first few argument sets for a call
const ARGS = (k, expr) => `(globalThis.__fcglArgs=globalThis.__fcglArgs||{},(globalThis.__fcglArgs[${JSON.stringify(k)}]=globalThis.__fcglArgs[${JSON.stringify(k)}]||[]).length<8&&globalThis.__fcglArgs[${JSON.stringify(k)}].push(${expr}))`;

const PATCHES = [
  // Does Coin ever ask for alpha blending, and with which factors? WebGL's default is
  // (ONE, ZERO), which draws the source opaque however many times BLEND is enabled.
  ['_glBlendFunc=(x0,x1)=>GLctx.blendFunc(x0,x1)',
   `_glBlendFunc=(x0,x1)=>{${HIT('blendFunc')};${ARGS('blendFunc', 'x0+","+x1')};return GLctx.blendFunc(x0,x1)}`],
  // Per capability: 3042 BLEND, 2896 LIGHTING, 2929 DEPTH_TEST, 2977 NORMAL_ARRAY.
  ['_glEnable=x0=>GLctx.enable(x0)',
   `_glEnable=x0=>{${HITV('enable_', 'x0')};return GLctx.enable(x0)}`],
  ['_glDisable=x0=>GLctx.disable(x0)',
   `_glDisable=x0=>{${HITV('disable_', 'x0')};return GLctx.disable(x0)}`],
  // Fixed-function array flags: whether normals are supplied for array-drawn geometry,
  // which decides whether the lighting shader has a normal to work with at all.
  ['var _emscripten_glEnableClientState=cap=>{',
   `var _emscripten_glEnableClientState=cap=>{${HITV('clientState_on_', 'cap')};`],
  ['function _emscripten_glNormalPointer(type,stride,pointer){',
   `function _emscripten_glNormalPointer(type,stride,pointer){${HIT('normalPointer')};`],
  // Coin's per-vertex colour path and the material calls that drive lighting.
  ['function _emscripten_glLightfv(light,pname,param){',
   `function _emscripten_glLightfv(light,pname,param){${HITV('lightfv_pname_', 'pname')};`],
  ['function _emscripten_glMaterialfv(face,pname,param){',
   `function _emscripten_glMaterialfv(face,pname,param){${HITV('materialfv_pname_', 'pname')};`],
  // Where does the diffuse colour AND its alpha come from? The patched shader picks
  // a_color when the colour client attribute is on, else u_materialDiffuse, and takes
  // v_color.w from whichever it picked. So: what alpha does Coin actually send, and how
  // many components does the colour attribute carry?
  ['var _emscripten_glColor4f=(r,g,b,a)=>{',
   `var _emscripten_glColor4f=(r,g,b,a)=>{${HIT('color4f')};${ARGS('color4f', 'r+","+g+","+b+","+a')};`],
  ['function _emscripten_glColorPointer(size,type,stride,pointer){',
   `function _emscripten_glColorPointer(size,type,stride,pointer){${HITV('colorPointer_size_', 'size')};`],
];

// Total coverage: wrap every gl* entry in the wasm import table. Per-function anchors
// miss calls that reach the glue through an alias or a generated wrapper (measured
// 2026-09-22: glColor4ub routes through a table, and its counter never moved while the
// colours plainly rendered). The import table is the one place every call must pass.
const IMPORTS = ['function getWasmImports(){ assignWasmImports();',
  `function getWasmImports(){ assignWasmImports();(()=>{globalThis.__fcGLE=GLEmulation;globalThis.__fcGLI=GLImmediate;globalThis.__fcglAll=globalThis.__fcglAll||{};globalThis.__fcglSeen=globalThis.__fcglSeen||{};` +
  `for(const k in wasmImports){if(!/^(emscripten_)?gl/.test(k))continue;const f=wasmImports[k];if(typeof f!=="function"||f.__fcCounted)continue;` +
  `const w=function(...a){globalThis.__fcglAll[k]=(globalThis.__fcglAll[k]||0)+1;` +
  `if(/Color4|Color3|Materialfv|Materialf$/.test(k)){const s=globalThis.__fcglSeen[k]=globalThis.__fcglSeen[k]||[];if(s.length<10)s.push(a.join(","));}` +
  // An ORDERED trace of the calls that decide whether a transparent object shows:
  // the blend state, the depth mask, the colour, and the draw itself.
  `if(/^(emscripten_)?gl(DepthMask|BlendFunc|Enable|Disable|Color4ub|DrawElements|DrawArrays|DepthFunc)$/.test(k)){` +
  `const t=globalThis.__fcglTrace=globalThis.__fcglTrace||[];if(t.length<4000)t.push(k.replace("emscripten_","")+"("+a.join(",")+")");}` +
  `return f.apply(this,a)};w.__fcCounted=true;wasmImports[k]=w;}})();`];

// --fix: the candidate repair for flat shading and lost transparency.
//
// Coin drives colour the fixed-function way: glEnable(GL_COLOR_MATERIAL) once, then the
// per-object colour through glColor4ub, which is why glMaterialfv is only ever called
// with ambient, specular and shininess and never with diffuse (measured 2026-09-22; the
// green box arrives as 26,230,26,77 and 77/255 is its 70% transparency). emscripten's
// emulation has no GL_COLOR_MATERIAL at all, so that colour never becomes the material
// the lighting shader multiplies by, and its alpha never becomes the fragment's alpha.
// This applies what the fixed-function pipeline does: with colour material on (default
// mode GL_AMBIENT_AND_DIFFUSE), glColor sets the ambient and diffuse material.
// Capture the state the emulation uses when it GENERATES its fixed-function shader, and
// the shader itself. This is the question behind "lighting is off": the emulation
// intercepts glEnable(GL_LIGHTING) and glEnable(GL_LIGHT0..7) in its own override and
// returns before the raw path, so counting the raw path says nothing. What decides the
// output is GLEmulation.lightingEnabled / lightEnabled at the moment the shader is built.
const SHADER = [
  // A statement in front of the array literal, so the expression it belongs to is untouched.
  ['}}var vsSource=[',
   '}}(globalThis.__fcShaderGen=globalThis.__fcShaderGen||[]).push({' +
   'lighting:GLEmulation.lightingEnabled,lights:Array.prototype.slice.call(GLEmulation.lightEnabled||[]),' +
   'twoSide:GLEmulation.lightModelTwoSide,clientAttribs:Array.prototype.slice.call(GLImmediate.enabledClientAttributes||[]),' +
   'matDiffuse:Array.prototype.slice.call(GLEmulation.materialDiffuse||[]),' +
   'clientColor:Array.prototype.slice.call(GLImmediate.clientColor||[])});var vsSource=[' ],
  // the generated source, as compiled
  ['GLctx.shaderSource(GL.shaders[shader],source)};_glCompileShader',
   '(globalThis.__fcShaderSrc=globalThis.__fcShaderSrc||[]).push(source);GLctx.shaderSource(GL.shaders[shader],source)};_glCompileShader'],
];

// The emulation REPLACES _glEnable at init (`var orig_glEnable=_glEnable;
// _glEnable=_emscripten_glEnable=cap=>{...}`), so a counter on the original only sees the
// caps the override forwards to real WebGL. The override is where GL_LIGHTING (2896) and
// GL_LIGHT0..7 (16384+) are handled, so that is where to ask whether Coin ever enables
// lighting at all.
const OVERRIDE = [
  // Two overrides are installed in sequence (the emulation's, then the texture-env JIT's).
  // The outermost one runs first, so it is the one that sees every call Coin makes.
  ['var glEnable=_glEnable;_glEnable=_emscripten_glEnable=cap=>{',
   'var glEnable=_glEnable;_glEnable=_emscripten_glEnable=cap=>{(globalThis.__fcEmuEnable=globalThis.__fcEmuEnable||{})[cap]=((globalThis.__fcEmuEnable||{})[cap]||0)+1;'],
  ['var glDisable=_glDisable;_glDisable=_emscripten_glDisable=cap=>{',
   'var glDisable=_glDisable;_glDisable=_emscripten_glDisable=cap=>{(globalThis.__fcEmuDisable=globalThis.__fcEmuDisable||{})[cap]=((globalThis.__fcEmuDisable||{})[cap]||0)+1;'],
];

// What normals does the GPU actually get? A flat box face should give one axis-aligned
// normal per face; if every face carries the same normal, flat surfaces all shade alike,
// which is what the desktop comparison showed (scratchpad/lightcmp.js).
const NORMALS = [
  ['function _emscripten_glNormalPointer(type,stride,pointer){',
   'function _emscripten_glNormalPointer(type,stride,pointer){' +
   'try{var __p=Number(pointer)/4,__h=(growMemViews(),HEAPF32),__st=(stride||12)/4,__n=[];' +
   'for(var __i=0;__i<8;__i++){__n.push(__h[__p+__i*__st].toFixed(2)+","+__h[__p+__i*__st+1].toFixed(2)+","+__h[__p+__i*__st+2].toFixed(2));}' +
   '(globalThis.__fcNormPtr=globalThis.__fcNormPtr||[]).length<14&&globalThis.__fcNormPtr.push({stride:stride,first:__n});}catch(e){}'],
];

const FIX = [
  ['var _emscripten_glColor4f=(r,g,b,a)=>{',
   'var _emscripten_glColor4f=(r,g,b,a)=>{if(GLEmulation.__fcColorMaterial!==false){' +
   'GLEmulation.materialDiffuse[0]=r;GLEmulation.materialDiffuse[1]=g;GLEmulation.materialDiffuse[2]=b;GLEmulation.materialDiffuse[3]=a;' +
   'GLEmulation.materialAmbient[0]=r;GLEmulation.materialAmbient[1]=g;GLEmulation.materialAmbient[2]=b;GLEmulation.materialAmbient[3]=a;}'],
  // GL_COLOR_MATERIAL is 2903; the emulation drops it, so its state is tracked here.
  ['_glEnable=x0=>{',
   '_glEnable=x0=>{if(x0==2903){GLEmulation.__fcColorMaterial=true}'],
  ['_glDisable=x0=>{',
   '_glDisable=x0=>{if(x0==2903){GLEmulation.__fcColorMaterial=false}'],
];

let src = fs.readFileSync(IN, 'utf8');
{
  const n = src.split(IMPORTS[0]).length - 1;
  if (n === 1) { src = src.replace(IMPORTS[0], IMPORTS[1]); console.log('import-table wrapper: applied'); }
  else console.log('import-table wrapper: NOT FOUND (' + n + ' matches)');
}
let applied = 0; const missing = [];
for (const [anchor, replacement] of PATCHES) {
  const n = src.split(anchor).length - 1;
  if (n !== 1) { missing.push(anchor.slice(0, 48) + '  (' + n + ' matches)'); continue; }
  src = src.replace(anchor, replacement);
  applied++;
}
for (const [anchor, replacement] of NORMALS) {
  const n = src.split(anchor).length - 1;
  if (n !== 1) { missing.push('NORMALS ' + anchor.slice(0, 44) + '  (' + n + ' matches)'); continue; }
  src = src.replace(anchor, replacement);
  applied++;
}
for (const [anchor, replacement] of OVERRIDE) {
  const n = src.split(anchor).length - 1;
  if (n !== 1) { missing.push('OVERRIDE ' + anchor.slice(0, 44) + '  (' + n + ' matches)'); continue; }
  src = src.replace(anchor, replacement);
  applied++;
}
for (const [anchor, replacement] of SHADER) {
  const n = src.split(anchor).length - 1;
  if (n !== 1) { missing.push('SHADER ' + anchor.slice(0, 44) + '  (' + n + ' matches)'); continue; }
  src = src.replace(anchor, replacement);
  applied++;
}
if (process.argv.includes('--fix')) {
  for (const [anchor, replacement] of FIX) {
    const n = src.split(anchor).length - 1;
    if (n !== 1) { missing.push('FIX ' + anchor.slice(0, 40) + '  (' + n + ' matches)'); continue; }
    src = src.replace(anchor, replacement);
    applied++;
  }
  console.log('candidate fix: applied');
}
fs.writeFileSync(OUT, src);
console.log('applied ' + applied + ' of ' + PATCHES.length + ' -> ' + OUT);
if (missing.length) { console.log('NOT FOUND:'); missing.forEach(x => console.log('  ' + x)); }
process.exit(missing.length ? 1 : 0);
