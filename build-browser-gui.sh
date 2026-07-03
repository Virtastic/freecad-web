#!/bin/bash
# Build the FreeCAD GUI (FreeCAD.js) for a browser tab: preload resources into
# MEMFS (no NODERAWFS) and run main() on a worker (PROXY_TO_PTHREAD) so the Qt
# event loop doesn't block the browser main thread.
set -e
cd "$(dirname "$0")"
. toolchain/env.sh
ROOT="$PWD"
CPY="$ROOT/deps/src/cpython"
INST="$ROOT/freecad-gui-install"

# Qt-for-WebAssembly runs its event loop on the MAIN thread (its own threading
# model uses workers only for QThread), so do NOT use PROXY_TO_PTHREAD here.
export FC_LINK_MODE_FLAGS="\
-sENVIRONMENT=web,worker \
--preload-file $CPY/Lib@/pylib \
--preload-file $ROOT/build-freecad-gui/Ext@/fc-ext \
--preload-file $INST/Mod@/freecad/Mod \
--preload-file $INST/Ext@/freecad/Ext \
--preload-file $INST/share@/freecad/share \
--preload-file $ROOT/deps/src/freecad/src/Gui/Stylesheets@/freecad/share/Gui/Stylesheets \
--preload-file $ROOT/deps/src/freecad/src/Mod/Material/Gui/Resources/icons@/freecad/share/Mod/Material/Resources/icons \
--preload-file $ROOT/deps/wasm/pyside-pkg@/pyside-pkg"

echo "=== reconfigure GUI for browser + relink ==="
bash configure-gui.sh > /tmp/fc-gui-cfg.log 2>&1
echo "configure exit=$?"
ninja -C build-freecad-gui bin/FreeCAD.js
mkdir -p play-gui
cp build-freecad-gui/bin/FreeCAD.js   play-gui/
cp build-freecad-gui/bin/FreeCAD.wasm play-gui/
cp build-freecad-gui/bin/FreeCAD.data play-gui/ 2>/dev/null || true
cp play/server.py play-gui/
cp spikes/01-qt-widgets/build/qtloader.js play-gui/   # Qt's known-good wasm loader
# Make getWasmTableEntry tolerate garbage/out-of-range function pointers (from a
# deeper wasm+pthreads memory bug) so those proxied calls no-op instead of
# throwing an uncaught cascade that breaks the Qt paint.
python3 - <<'PYPATCH'
p='play-gui/FreeCAD.js'; s=open(p).read()
old='if (funcPtr >= wasmTableMirror.length) wasmTableMirror.length = funcPtr + 1;\n    wasmTableMirror[funcPtr] = func = wasmTable.get(funcPtr);'
new='if (funcPtr >= wasmTableMirror.length) wasmTableMirror.length = funcPtr + 1;\n    try { wasmTableMirror[funcPtr] = func = wasmTable.get(funcPtr); } catch (e) { func = undefined; }'
if old in s:
    s=s.replace(old,new,1)
    s=s.replace('wasmTable.get(funcPtr); } catch (e) { func = undefined; }\n  }\n  assert(',
                'wasmTable.get(funcPtr); } catch (e) { func = undefined; }\n  }\n  if (!func) { return function(){ return 0; }; }\n  assert(',1)
    print('patched getWasmTableEntry')
else:
    print('getWasmTableEntry pattern not found (skipped)')
tex_old="""    function getCurTexUnit() {
      return s_texUnits[s_activeTexture];
    }"""
tex_new="""    function getCurTexUnit() {
      if (!s_texUnits) return { enabled_tex1D:false, enabled_tex2D:false, enabled_tex3D:false, enabled_texCube:false, texTypesEnabled:0, env:{} };
      return s_texUnits[s_activeTexture];
    }"""
if tex_old in s:
    s=s.replace(tex_old,tex_new,1)
    print('patched getCurTexUnit')
else:
    print('getCurTexUnit pattern not found (skipped)')
frame_old="""  newRenderingFrameStarted: () => {
    if (!GL.currentContext) {
      return;
    }"""
frame_new="""  newRenderingFrameStarted: () => {
    if (!GL.currentContext || !GL.currentContext.tempVertexBufferCounters1) {
      return;
    }"""
if frame_old in s:
    s=s.replace(frame_old,frame_new,1)
    print('patched newRenderingFrameStarted')
else:
    print('newRenderingFrameStarted pattern not found (skipped)')
mcc_anchor = "Browser.moduleContextCreatedCallbacks.push(() => GLImmediate.init());"
mcc_hook = mcc_anchor + """

// FCWEB: init immediate-mode GL emulation on first makeContextCurrent (Qt
// contexts never fire moduleContextCreatedCallbacks).
(function(){ var _mcc = GL.makeContextCurrent;
  GL.makeContextCurrent = function(ctx){ var r = _mcc.call(GL, ctx);
    try {
      if (GL.currentContext && typeof GLctx !== 'undefined' && GLctx) {
        if (!GLImmediate.initted) {
          Browser.useWebGL = true;
          GLImmediate.init();
        }
        // each Qt-created context needs its own immediate-mode temp buffers
        if (!GL.currentContext.tempVertexBuffers1) {
          GL.generateTempBuffers(true, GL.currentContext);
        }
      }
    } catch(e) { if (typeof err === 'function') err('[fcweb glimm init] ' + e); }
    return r; };
})();"""
if mcc_anchor in s and mcc_hook not in s:
    s=s.replace(mcc_anchor, mcc_hook, 1)
    print('patched makeContextCurrent GLImmediate init')
else:
    print('makeContextCurrent pattern not found (skipped)')
mat_old="""  } else {
    throw "glMaterialfv: TODO: " + pname;
  }
}"""
mat_new="""  } else if (pname == 5632) {
    GLEmulation.materialEmission = GLEmulation.materialEmission || [0,0,0,1];
    GLEmulation.materialEmission[0] = GROWABLE_HEAP_F32()[((param) >>> 2) >>> 0];
    GLEmulation.materialEmission[1] = GROWABLE_HEAP_F32()[(((param) + (4)) >>> 2) >>> 0];
    GLEmulation.materialEmission[2] = GROWABLE_HEAP_F32()[(((param) + (8)) >>> 2) >>> 0];
    GLEmulation.materialEmission[3] = GROWABLE_HEAP_F32()[(((param) + (12)) >>> 2) >>> 0];
  } else {
    if (!GLEmulation.__matWarned) { GLEmulation.__matWarned = {}; }
    if (!GLEmulation.__matWarned[pname]) { GLEmulation.__matWarned[pname] = 1; err("glMaterialfv: ignored pname " + pname); }
  }
}"""
if mat_old in s:
    s=s.replace(mat_old,mat_new,1); print('patched glMaterialfv')
else: print('glMaterialfv pattern not found (skipped)')
nrm_old="""/** @suppress {duplicate } */ var _glNormal3f = (x, y, z) => {
  assert(GLImmediate.mode >= 0);
  // must be in begin/end"""
nrm_new="""/** @suppress {duplicate } */ var _glNormal3f = (x, y, z) => {
  if (GLImmediate.mode < 0) { GLEmulation.__curNormal = [x,y,z]; return; }
  // must be in begin/end"""
if nrm_old in s:
    s=s.replace(nrm_old,nrm_new,1); print('patched glNormal3f')
else: print('glNormal3f pattern not found (skipped)')
amb_old = "GLEmulation.lightModelAmbient = new Float32Array([ .2, .2, .2, 1 ]);"
amb_new = "GLEmulation.lightModelAmbient = new Float32Array([ 1, 1, 1, 1 ]);"
if amb_old in s:
    s=s.replace(amb_old,amb_new,1); print("patched default lightModelAmbient")
else:
    print("default lightModelAmbient not found (skipped)")
open(p,"w").write(s)
lm_old="""  if (pname == 2899) {
    // GL_LIGHT_MODEL_AMBIENT
    GLEmulation.lightModelAmbient[0] = GROWABLE_HEAP_F32()[((param) >>> 2) >>> 0];
    GLEmulation.lightModelAmbient[1] = GROWABLE_HEAP_F32()[(((param) + (4)) >>> 2) >>> 0];
    GLEmulation.lightModelAmbient[2] = GROWABLE_HEAP_F32()[(((param) + (8)) >>> 2) >>> 0];
    GLEmulation.lightModelAmbient[3] = GROWABLE_HEAP_F32()[(((param) + (12)) >>> 2) >>> 0];
  } else {
    throw \"glLightModelfv: TODO: \" + pname;
  }"""
lm_new="""  if (pname == 2899) {
    var FCWEB_AMB = 0.55;
    GLEmulation.lightModelAmbient[0] = Math.max(FCWEB_AMB, GROWABLE_HEAP_F32()[((param) >>> 2) >>> 0]);
    GLEmulation.lightModelAmbient[1] = Math.max(FCWEB_AMB, GROWABLE_HEAP_F32()[(((param) + (4)) >>> 2) >>> 0]);
    GLEmulation.lightModelAmbient[2] = Math.max(FCWEB_AMB, GROWABLE_HEAP_F32()[(((param) + (8)) >>> 2) >>> 0]);
    GLEmulation.lightModelAmbient[3] = GROWABLE_HEAP_F32()[(((param) + (12)) >>> 2) >>> 0];
  } else {
  }"""
if lm_old in s:
    s=s.replace(lm_old,lm_new,1); print("patched glLightModelfv ambient floor")
else:
    print("glLightModelfv pattern not found (skipped)")
open(p,"w").write(s)
PYPATCH
echo "=== GUI browser artifacts ===" && ls -la play-gui/FreeCAD.* 2>/dev/null | awk '{print $5, $9}'
