#!/usr/bin/env python3
"""Re-apply the GL fixes that live in the linked FreeCAD.js, not in any source file.

These patch emscripten's generated GL-emulation JS, so they cannot be expressed in
pre-gui.js (which is inlined *before* that code) or in the C++ tree. They were applied
by hand to the shipped FreeCAD.js, which means **every relink silently loses them** --
the symptom is a boot-time storm of

    TypeError: Cannot read properties of null (reading '0')
        at getCurTexUnit ... at hook_disable ... at _emscripten_glDisable

followed by FreeCAD.newDocument() never returning. Nothing in the build output warns
about it, so run this on bin/FreeCAD.js after every link.

Six behavioural fixes plus four silenced warnings (Coin drives the fixed-function
pipeline in ways emscripten warns about on every call, which floods the console):

  getCurTexUnit    Returns a neutral texture unit when s_texUnits has not been set up
                   yet. Without it, texture-env hooks dereference undefined during the
                   first frames and the 3D view never comes up.

  getWasmTableEntry  Tolerates a function-pointer that is not in the table: the lookup
                     is wrapped in try/catch and a missing entry yields a no-op stub
                     returning 0, instead of throwing. Without it an indirect call
                     through a stale pointer takes down whatever was running -- this is
                     the "null function trap" that used to abort document creation.

  glGet legacy     Answers the fixed-function queries Coin still makes -- CULL_FACE_MODE
  queries          (-> BACK), POLYGON_MODE (-> FILL), and two others -- which WebGL
                   answers with null. The stock path turns that into GL_INVALID_ENUM and
                   returns WITHOUT writing the output pointer, leaving the caller reading
                   whatever was already there.

  GL default       Brightens emscripten's fixed-function defaults (ambient light and
  lighting         material ambient) to what Coin's shading expects. Purely visual, but
                   without it models render markedly darker than the desktop.

  immediate-mode   Never reuses whatever shader happens to be bound for immediate-mode
  program          drawing. Coin binds its own programs, and inheriting one leaves the
                   fixed-function geometry drawn with the wrong shader.

  flush lighting   Turns fixed-function lighting on exactly when the immediate-mode
                   NORMAL array is supplied (and enables light 0 / two-sided the first
                   time), binds the renderer's own program before drawing, and drops
                   non-integer vertex counts. This is the "renders once then blank"
                   family of viewport bugs.

  glBegin modes    Maps GL_QUAD_STRIP to TRIANGLE_STRIP and GL_POLYGON to TRIANGLE_FAN.
                   emscripten aborts on both, and Coin emits them -- this is the
                   GL_QUAD_STRIP abort hit when opening the bundled examples.

  glColor material Makes glColor also set material diffuse/ambient, i.e. the
                   GL_COLOR_MATERIAL behaviour Coin relies on. Without it lit geometry
                   ignores the colour that was just set.

  glEnd buffer     Unbinds a left-over ARRAY_BUFFER before flushing. A stale binding
                   starves the immediate-mode vertex upload, which is the root cause of
                   the viewport rendering once and then going blank.

  GLImmediate      Caches the result of GLctx.isProgram() per renderer, and drops a
  renderer reuse   cached renderer whose program or GL context is no longer valid.
                   The isProgram() call is a GPU round-trip on every flush -- this is
                   the "interaction 1 -> 38 fps" fix -- and the validity check is what
                   stops a renderer from a dead context being reused.

Usage: patch-freecad-js.py <FreeCAD.js> [--check]
"""
import re
import sys
import pathlib

PATCHES = [
    (
        'getCurTexUnit null-guard',
        'function getCurTexUnit(){return s_texUnits[s_activeTexture]}',
        'function getCurTexUnit(){if(!s_texUnits)return{enabled_tex1D:false,'
        'enabled_tex2D:false,enabled_tex3D:false,enabled_texCube:false,'
        'texTypesEnabled:0,env:{}};return s_texUnits[s_activeTexture]}',
    ),
    (
        'GLImmediate.getRenderer validity cache',
        'getRenderer(){if(GLImmediate.currentRenderer){return GLImmediate.currentRenderer}',
        'getRenderer(){if(GLImmediate.currentRenderer){var _r0=GLImmediate.currentRenderer,'
        '_vp0;if(_r0._fcProgOK===_r0.program&&_r0._fcCtx===GLctx){_vp0=true}else{try{'
        '_vp0=_r0.program&&GLctx.isProgram(_r0.program)}catch(_e){_vp0=false}if(_vp0){'
        '_r0._fcProgOK=_r0.program;_r0._fcCtx=GLctx}}if(_vp0){return _r0}'
        'GLImmediate.currentRenderer=null}',
    ),
    (
        'cached renderer validity check',
        'var renderer=keyView.get();if(!renderer){',
        'var renderer=keyView.get();if(renderer){var _vp1;if(renderer._fcProgOK==='
        'renderer.program&&renderer._fcCtx===GLctx){_vp1=true}else{try{_vp1='
        'renderer.program&&GLctx.isProgram(renderer.program)}catch(_e){_vp1=false}'
        'if(_vp1){renderer._fcProgOK=renderer.program;renderer._fcCtx=GLctx}}'
        'if(!_vp1)renderer=null}if(!renderer){',
    ),
    (
        'getWasmTableEntry null-function guard',
        'wasmTableMirror[funcPtr]=func=wasmTable.get(funcPtr);'
        'if(Asyncify.isAsyncExport(func)){wasmTableMirror[funcPtr]=func='
        'Asyncify.makeAsyncFunction(func)}}return func}',
        'try{wasmTableMirror[funcPtr]=func=wasmTable.get(funcPtr)}catch(e){func=undefined}'
        'if(func&&Asyncify.isAsyncExport(func)){wasmTableMirror[funcPtr]=func='
        'Asyncify.makeAsyncFunction(func)}}if(!func){return function(){return 0}}return func}',
    ),
    (
        'glGet legacy fixed-function queries',
        'ret=name_==33307?3:0;break}if(ret===undefined){var result=GLctx.getParameter(name_);',
        'ret=name_==33307?3:0;break}if(ret===undefined){if(name_===2834){ret=1029}'
        'else if(name_===2850){ret=6914}else if(name_===3377){ret=8}'
        'else if(name_===3121){ret=0}}if(ret===undefined){'
        'var result=GLctx.getParameter(name_);',
    ),
    (
        'GL emulation default lighting',
        'GLEmulation.lightModelAmbient=new Float32Array([.2,.2,.2,1]);'
        'GLEmulation.materialAmbient=new Float32Array([.2,.2,.2,1]);',
        'GLEmulation.lightModelAmbient=new Float32Array([.45,.45,.45,1]);'
        'GLEmulation.materialAmbient=new Float32Array([.8,.8,.8,1]);',
    ),
    (
        'silence the GL-emulation banner',
        'new Float32Array([0,0,1,0])}err("WARNING: using emscripten GL emulation. '
        'This is a collection of limited workarounds, do not expect it to work.");'
        'var validCapabilities=',
        'new Float32Array([0,0,1,0])}0;var validCapabilities=',
    ),
    (
        'silence unhandled-pname TexEnv warnings',
        'default:err("WARNING: Unhandled `pname` in call to `glTexEnvf`.")}',
        'default:0}',
    ),
    (
        'silence unhandled-pname TexEnvfv warning',
        'default:err("WARNING: Unhandled `pname` in call to `glTexEnvfv`.")}',
        'default:0}',
    ),
    (
        'silence unhandled-pname TexEnvi warning',
        'default:err("WARNING: Unhandled `pname` in call to `glTexEnvi`.")}',
        'default:0}',
    ),
    (
        'immediate-mode renderer builds its own program',
        'createRenderer(renderer){var useCurrProgram=!!GL.currProgram;',
        'createRenderer(renderer){var useCurrProgram=false;',
    ),
    (
        'GLImmediate.flush lighting + program binding',
        'flush(numProvidedIndexes,startIndex=0,ptr=0){var renderer=GLImmediate.getRenderer();var numVertices=4*GLImmediate.vertexCounter/GLImmediate.stride;if(!numVertices)return;var emulatedElementArrayBuffer=false;',
        'flush(numProvidedIndexes,startIndex=0,ptr=0){try{if(typeof GLEmulation!=="undefined"&&GLImmediate.enabledClientAttributes){var _hasN=!!GLImmediate.enabledClientAttributes[GLImmediate.NORMAL!=null?GLImmediate.NORMAL:1];if(GLEmulation.lightingEnabled!==_hasN){GLEmulation.lightingEnabled=_hasN;GLImmediate.currentRenderer=null;}if(_hasN&&GLEmulation.lightEnabled&&!GLEmulation.lightEnabled[0]){GLEmulation.lightEnabled[0]=true;GLEmulation.lightModelTwoSide=1;GLImmediate.currentRenderer=null;}}}catch(_e){}var renderer=GLImmediate.getRenderer();if(renderer&&renderer.program){GLctx.useProgram(renderer.program)}var numVertices=4*GLImmediate.vertexCounter/GLImmediate.stride;if(!numVertices)return;if(numVertices!==(numVertices|0))return;var emulatedElementArrayBuffer=false;',
    ),
    (
        'glBegin: map QUAD_STRIP and POLYGON',
        'var _glBegin=mode=>{GLImmediate.enabledClientAttributes_preBegin=',
        'var _glBegin=mode=>{if(mode===8)mode=5;else if(mode===9)mode=6;'
        'GLImmediate.enabledClientAttributes_preBegin=',
    ),
    (
        'glColor drives material colour',
        'GLImmediate.clientColor[3]=a}};var _glColor3f=',
        'GLImmediate.clientColor[3]=a}if(GLEmulation&&GLEmulation.materialDiffuse){GLEmulation.materialDiffuse[0]=r;GLEmulation.materialDiffuse[1]=g;GLEmulation.materialDiffuse[2]=b;GLEmulation.materialDiffuse[3]=a;GLEmulation.materialAmbient[0]=r;GLEmulation.materialAmbient[1]=g;GLEmulation.materialAmbient[2]=b;GLEmulation.materialAmbient[3]=a}};var _glColor3f=',
    ),
    (
        'glEnd clears a stale ARRAY_BUFFER binding',
        'GLImmediate.lastVertex=GLImmediate.vertexCounter/(GLImmediate.stride>>2);GLImmediate.flush();',
        'GLImmediate.lastVertex=GLImmediate.vertexCounter/(GLImmediate.stride>>2);if(GLctx.currentArrayBufferBinding){GLctx.bindBuffer(GLctx.ARRAY_BUFFER,null);GLctx.currentArrayBufferBinding=null;}GLImmediate.flush();',
        # line batching inserts between this clause and flush(), so the whole
        # replacement no longer appears contiguously -- detect the clause itself
        'if(GLctx.currentArrayBufferBinding){GLctx.bindBuffer(GLctx.ARRAY_BUFFER,null);GLctx.currentArrayBufferBinding=null;}',
    ),
    (
        'glMaterialfv: EMISSION and AMBIENT_AND_DIFFUSE',
        'GLEmulation.materialShininess[0]=HEAPF32[param>>2]}else{0}};var _emscripten_glMaterialfv=',
        'GLEmulation.materialShininess[0]=HEAPF32[param>>2]}else if(pname==5632){GLEmulation.materialEmission[0]=HEAPF32[param>>2];GLEmulation.materialEmission[1]=HEAPF32[param+4>>2];GLEmulation.materialEmission[2]=HEAPF32[param+8>>2];GLEmulation.materialEmission[3]=HEAPF32[param+12>>2]}else if(pname==5634){var _r=HEAPF32[param>>2],_g=HEAPF32[param+4>>2],_b=HEAPF32[param+8>>2],_a=HEAPF32[param+12>>2];GLEmulation.materialAmbient[0]=_r;GLEmulation.materialAmbient[1]=_g;GLEmulation.materialAmbient[2]=_b;GLEmulation.materialAmbient[3]=_a;GLEmulation.materialDiffuse[0]=_r;GLEmulation.materialDiffuse[1]=_g;GLEmulation.materialDiffuse[2]=_b;GLEmulation.materialDiffuse[3]=_a}else{0}};var _emscripten_glMaterialfv=',
    ),
    (
        'glNormal3f outside begin/end',
        'var _glNormal3f=(x,y,z)=>{GLImmediate.vertexData[GLImmediate.vertexCounter++]=x;',
        'var _glNormal3f=(x,y,z)=>{if(GLImmediate.mode<0){GLEmulation.__curNormal=[x,y,z];return}GLImmediate.vertexData[GLImmediate.vertexCounter++]=x;',
    ),
    (
        'init immediate mode on context switch (FCWEBMCC)',
        'GLImmediate.init());GLEmulation.init();for(var i=0;i<32;++i)',
        'GLImmediate.init());(function(){var _mcc=GL.makeContextCurrent;GL.makeContextCurrent=function(ctx){var r=_mcc.call(GL,ctx);try{if(GL.currentContext&&typeof GLctx!=="undefined"&&GLctx){if(!GLImmediate.initted){Browser.useWebGL=true;GLImmediate.init()}if(!GL.currentContext.tempVertexBuffers1){GL.generateTempBuffers(true,GL.currentContext)}}}catch(e){}return r}})();/*FCWEBMCC*/GLEmulation.init();for(var i=0;i<32;++i)',
    ),
]

# Coin exercises corners of the fixed-function API that emscripten implements by
# THROWING. A throw from inside a GL call unwinds through Coin's render traversal and
# takes the viewport (or the whole document) with it, so each becomes a no-op.
_TODO_THROWS = [
    'throw"glLightModelf: TODO: "+pname',
    'throw"glLightModelfv: TODO: "+pname',
    'throw"glLightfv: TODO: "+pname',
    'throw"glMaterialfv: TODO"+face',
    'throw"glMaterialfv: TODO: "+pname',
    'throw"glTexCoord3f: TODO"',
    'throw"glTexCoord4f: TODO"',
    'throw"glTexGenfv: TODO"',
    'throw"glTexGeni: TODO"',
]
PATCHES += [(t.split('"')[1].split(':')[0] + ' must not throw', t, '0') for t in _TODO_THROWS]


def apply(text, _passes=3):
    """Return (patched_text, [status per patch]). Idempotent.

    Applied repeatedly to a fixpoint: some sites only appear once an earlier patch has
    run (the glMaterialfv extension matches text that the throw->no-op patch creates),
    and hard-coding a working order is a trap the next patch would fall into.
    """
    for _ in range(_passes - 1):
        text, st = _apply_once(text)
        if all(s != 'applied' for _, s in st):
            break
    return _apply_once(text)


# ---- immediate-mode line batching -------------------------------------------------
# Coin draws every EDGE as its own glBegin(GL_LINE_STRIP)/glEnd. On BIMExample that is
# 80,030 of 86,122 draws -- 93 percent -- each carrying a full bufferSubData + attribute
# setup + draw + teardown, and the frame is draw-call bound (a CPU profile shows the main
# thread 68 percent IDLE). Deferring a two-vertex block so the next identical one appends
# to the same accumulator, then flushing once as GL_LINES, takes the heavy scene from
# ~4100 draws and ~10 fps to ~470 draws and 21-34 fps, p95 frame 119 ms -> 20 ms.
#
# THE ONE COST, measured and deliberate: GL_LINE_STRIP(2) and GL_LINES(2) do NOT
# rasterise identically on ANGLE/Metal. 128 pixels of 4,032,000 shift by one from the
# mode conversion ALONE, with zero batching -- proved by disabling the merge and keeping
# the conversion. Merging brings it to 279, i.e. 0.0069 percent, confined to hairline
# axis markers and leader lines which stay present and legible. No geometry, dimension or
# measurement is affected. ?nomerge=1 turns it off at runtime.
# Pixel-identical batching would need indexed draws with PRIMITIVE_RESTART so the
# primitive stays a real LINE_STRIP; that is the path if those 279 pixels ever matter.
#
# The merge key covers everything renderer.prepare() applies late (both matrices by
# CONTENT not just version, material and lighting state), a block that turns out to have
# more than two vertices is split back out, and a deferred block tears down exactly like
# an undeferred one -- each of those was a real bug found by pixel diff.
OLD_END_MERGE = 'var _glEnd=()=>{GLImmediate.prepareClientAttributes(GLImmediate.rendererComponents[GLImmediate.VERTEX],true);GLImmediate.firstVertex=0;GLImmediate.lastVertex=GLImmediate.vertexCounter/(GLImmediate.stride>>2);if(GLctx.currentArrayBufferBinding){GLctx.bindBuffer(GLctx.ARRAY_BUFFER,null);GLctx.currentArrayBufferBinding=null;}GLImmediate.flush();GLImmediate.disableBeginEndClientAttributes();GLImmediate.mode=-1;GLImmediate.enabledClientAttributes=GLImmediate.enabledClientAttributes_preBegin;GLImmediate.clientAttributes=GLImmediate.clientAttributes_preBegin;GLImmediate.currentRenderer=null;GLImmediate.modifiedClientAttributes=true}'
NEW_END_MERGE = 'GLImmediate.__mrgN=0;GLImmediate.__mrgPend=false;GLImmediate.__mrgPrevVC=0;GLImmediate.__mrgSnap=null;GLImmediate.__mrgOn=!/[?&]nomerge=1/.test(location.search);globalThis.__GLI=GLImmediate;GLImmediate.__mrgPrev=new Float64Array(128);GLImmediate.__mrgHave=false;GLImmediate.__mrgCmp=function(commit){var E=(typeof GLEmulation!=="undefined")?GLEmulation:null;var a=GLImmediate.__mrgPrev,n=0,same=GLImmediate.__mrgHave,v,i,j;function put(x){x=+x||0;if(a[n]!==x){same=false;if(commit)a[n]=x}n++}put(GLImmediate.matrixVersion[0]);put(GLImmediate.matrixVersion[1]);for(i=0;i<2;i++){v=GLImmediate.matrix[i];if(v)for(j=0;j<16;j++)put(v[j])}if(E){put(E.lightingEnabled?1:0);put(E.lightModelTwoSide);var ks=["materialAmbient","materialDiffuse","materialEmission","materialSpecular","materialShininess","lightModelAmbient"];for(i=0;i<ks.length;i++){v=E[ks[i]];if(v)for(j=0;j<v.length;j++)put(v[j])}if(E.lightEnabled)for(i=0;i<E.lightEnabled.length;i++)put(E.lightEnabled[i]?1:0)}if(commit)GLImmediate.__mrgHave=true;return same};GLImmediate.__mf=function(){if(GLImmediate.__mrgPend)GLImmediate.__flushMerged()};GLImmediate.__flushMerged=()=>{if(!GLImmediate.__mrgPend)return;var S=GLImmediate.__mrgSnap;GLImmediate.__mrgPend=false;GLImmediate.__mrgN=0;GLImmediate.__mrgSnap=null;GLImmediate.__mrgHave=false;var kCA=GLImmediate.clientAttributes,kECA=GLImmediate.enabledClientAttributes,kRC=GLImmediate.rendererComponents,kMode=GLImmediate.mode,kStride=GLImmediate.stride;GLImmediate.clientAttributes=S.ca;GLImmediate.enabledClientAttributes=S.eca;GLImmediate.rendererComponents=S.rc;GLImmediate.stride=S.stride;GLImmediate.currentRenderer=null;GLImmediate.modifiedClientAttributes=true;GLImmediate.firstVertex=0;GLImmediate.lastVertex=GLImmediate.vertexCounter/(GLImmediate.stride>>2);GLImmediate.mode=1;GLImmediate.flush();GLImmediate.disableBeginEndClientAttributes();GLImmediate.clientAttributes=kCA;GLImmediate.enabledClientAttributes=kECA;GLImmediate.rendererComponents=kRC;GLImmediate.stride=kStride;GLImmediate.mode=kMode;GLImmediate.currentRenderer=null;GLImmediate.modifiedClientAttributes=true;GLImmediate.vertexCounter=0;GLImmediate.__mrgPrevVC=0};var _glEnd=()=>{GLImmediate.prepareClientAttributes(GLImmediate.rendererComponents[GLImmediate.VERTEX],true);GLImmediate.firstVertex=0;GLImmediate.lastVertex=GLImmediate.vertexCounter/(GLImmediate.stride>>2);if(GLctx.currentArrayBufferBinding){GLctx.bindBuffer(GLctx.ARRAY_BUFFER,null);GLctx.currentArrayBufferBinding=null;}if(GLImmediate.__mrgOn&&GLImmediate.mode===3&&GLImmediate.stride&&!(typeof GLEmulation!=="undefined"&&GLEmulation.lightingEnabled)&&(GLImmediate.vertexCounter-GLImmediate.__mrgPrevVC)/(GLImmediate.stride>>2)===2){GLImmediate.__mrgPend=true;GLImmediate.__mrgN++;GLImmediate.__mrgSnap={ca:GLImmediate.clientAttributes,eca:GLImmediate.enabledClientAttributes,rc:GLImmediate.rendererComponents,stride:GLImmediate.stride};GLImmediate.__mrgCmp(true);GLImmediate.disableBeginEndClientAttributes();GLImmediate.mode=-1;GLImmediate.enabledClientAttributes=GLImmediate.enabledClientAttributes_preBegin;GLImmediate.clientAttributes=GLImmediate.clientAttributes_preBegin;GLImmediate.currentRenderer=null;GLImmediate.modifiedClientAttributes=true;return;}if(GLImmediate.__mrgPend){var __m=GLImmediate.mode,__vc=GLImmediate.vertexCounter,__base=GLImmediate.__mrgPrevVC;GLImmediate.vertexCounter=__base;GLImmediate.__flushMerged();if(__vc>__base){GLImmediate.vertexData.copyWithin(0,__base,__vc);}GLImmediate.vertexCounter=__vc-__base;GLImmediate.mode=__m;GLImmediate.firstVertex=0;GLImmediate.lastVertex=GLImmediate.vertexCounter/(GLImmediate.stride>>2);}GLImmediate.flush();GLImmediate.disableBeginEndClientAttributes();GLImmediate.mode=-1;GLImmediate.enabledClientAttributes=GLImmediate.enabledClientAttributes_preBegin;GLImmediate.clientAttributes=GLImmediate.clientAttributes_preBegin;GLImmediate.currentRenderer=null;GLImmediate.modifiedClientAttributes=true}'
OLD_VC_MERGE = 'GLImmediate.mode=mode;GLImmediate.vertexCounter=0;'
NEW_VC_MERGE = 'GLImmediate.mode=mode;if(GLImmediate.__mrgPend&&mode===3&&GLImmediate.__mrgSnap&&GLImmediate.__mrgCmp(false)){GLImmediate.__mrgPrevVC=GLImmediate.vertexCounter;}else{GLImmediate.__mf();GLImmediate.vertexCounter=0;GLImmediate.__mrgPrevVC=0;}'
DRAINS_MERGE = [('var _glDrawArrays=(mode,first,count)=>{if(GLImmediate.totalEnabledClientAttribu', 'var _glDrawArrays=(mode,first,count)=>{GLImmediate.__mf();if(GLImmediate.totalEnabledClientAttribu'), ('var _glDrawElements=(mode,count,type,indices,start,end)=>{if(GLImmediate.totalEnabledClientAttribu', 'var _glDrawElements=(mode,count,type,indices,start,end)=>{GLImmediate.__mf();if(GLImmediate.totalEnabledClientAttribu'), ('var _glEnableClientState=cap=>{var attrib=GLEmulation.getAttributeFromC', 'var _glEnableClientState=cap=>{GLImmediate.__mf();var attrib=GLEmulation.getAttributeFromC'), ('var _glDisableClientState=cap=>{var attrib=GLEmulation.getAttributeFromC', 'var _glDisableClientState=cap=>{GLImmediate.__mf();var attrib=GLEmulation.getAttributeFromC')]

MERGE_PATCHES = [
    ('immediate-mode line batching: glEnd defers', OLD_END_MERGE, NEW_END_MERGE),
    ('immediate-mode line batching: glBegin continues', OLD_VC_MERGE, NEW_VC_MERGE),
]
MERGE_PATCHES += [('line batching drain: ' + o.split('=')[0].replace('var _gl', 'gl'),
                   o, n) for o, n in DRAINS_MERGE]
PATCHES += MERGE_PATCHES


# Invariants a correctly patched file must satisfy, checked AFTER everything runs.
#
# The per-patch status cannot be trusted on its own. Every throw-removal patch replaces
# its site with the literal "0", and "0" occurs all over minified JS, so the
# "elif new in text -> already applied" arm fires for ANY of them whose search text stops
# matching. Building with ALLOW_MEMORY_GROWTH did exactly that: heap access became
# GROWABLE_HEAP_F32()[x>>>2>>>0] instead of HEAPF32[x>>2], nine throw patches reported
# "already applied", and the file still threw from nine GL entry points. A throw inside a
# GL call unwinds through Coin and takes the viewport with it.
#
# So the invariant is checked against the thing itself, not against the status: none of
# the exact throw sites may survive. (Other GL throws DO legitimately remain --
# glDrawBuffer, glGetTexLevelParameteriv, glTexImage1D are not on Coin's path and are
# deliberately untouched -- so this must be the specific list, not /throw"gl/.)
def check_postconditions(text):
    """Return a list of (what, why, count) for every invariant the file violates."""
    bad = []
    for t in _TODO_THROWS:
        n = text.count(t)
        if n:
            bad.append((t, 'Coin calls this; a throw here kills the viewport', n))
    if '__flushMerged' not in text:
        bad.append(('immediate-mode line batching', 'absent -- the heavy-scene draw-call reduction is not in this build', 1))
    n = len(re.findall(r'GROWABLE_HEAP_[A-Z0-9]+\(\)', text))
    if n:
        bad.append(('GROWABLE_HEAP accessors', 'built with ALLOW_MEMORY_GROWTH -- the '
                    'heap-access form changed, so this patch table does not apply and '
                    'must be re-derived for it', n))
    return bad


def _apply_once(text):
    status = []
    for entry in PATCHES:
        name, old, new = entry[0], entry[1], entry[2]
        # a 4th field is the text that proves the fix is in effect, for when a
        # LATER patch rewrites the surroundings so `new` no longer appears whole
        marker = entry[3] if len(entry) > 3 else new
        # Check for the UNPATCHED site first. Testing "is the replacement present"
        # first would misfire for short replacements -- "0;" occurs throughout
        # minified JS -- and silently skip a patch that was never applied.
        if old in text:
            text = text.replace(old, new, 1)
            status.append((name, 'applied'))
        elif marker in text:
            status.append((name, 'already applied'))
        else:
            status.append((name, 'NOT FOUND'))
    return text, status


def main():
    p = pathlib.Path(sys.argv[1])
    check = '--check' in sys.argv
    src = p.read_text(errors='replace')
    out, status = apply(src)
    missing = [n for n, s in status if s == 'NOT FOUND']
    for n, s in status:
        print('  %-38s %s' % (n, s))
    if missing:
        print('ERROR: %d patch site(s) not found -- emscripten output changed, '
              'the fixes need re-deriving' % len(missing), file=sys.stderr)
        return 1
    violations = check_postconditions(out)
    for pat, why, n in violations:
        print('ERROR: %d x /%s/ still present -- %s' % (n, pat, why), file=sys.stderr)
    if violations:
        print('ERROR: the per-patch status above is NOT sufficient; these invariants '
              'are what the patches exist to guarantee', file=sys.stderr)
        return 1
    if not check and out != src:
        p.write_text(out)
        print('patched %s' % p)
    return 0


def selftest():
    # Fixture is built from the patch table itself, so it cannot go stale as patches
    # are added. Each OLD string must be found and replaced exactly once.
    src = ''.join(e[1] for e in PATCHES)
    out, status = apply(src)
    # after the fixpoint loop the final pass reports 'already applied'; what matters
    # is that no site was missed
    bad = [(n, st) for n, st in status if st == 'NOT FOUND']
    assert not bad, bad
    for e in PATCHES:
        name, old, new = e[0], e[1], e[2]
        assert new in out, name

    # idempotent: a second pass must change nothing
    out2, status2 = apply(out)
    assert out2 == out, 'not idempotent'

    # a file missing every site must be reported, not silently "fixed"
    _, s3 = apply('function unrelated(){}')
    assert all(st == 'NOT FOUND' for _, st in s3), s3

    # NOTE: patches whose replacement is just "0" cannot be distinguished as
    # "already applied" vs "site absent" by content alone -- "0" is everywhere in
    # minified JS. That is why apply() tests for the UNPATCHED site first; the
    # worst case is a cosmetic status, never a missed or double substitution.

    print('patch-freecad-js selftest OK (%d patches)' % len(PATCHES))


if __name__ == '__main__':
    if len(sys.argv) == 2 and sys.argv[1] == '--selftest':
        selftest()
    else:
        sys.exit(main())
