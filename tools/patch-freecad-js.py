#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) Virtastic
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
        'GLEmulation.materialShininess[0]=HEAPF32[param>>2]}else{throw"glMaterialfv: TODO: "+pname}};var _emscripten_glMaterialfv=',
        'GLEmulation.materialShininess[0]=HEAPF32[param>>2]}else if(pname==5632){GLEmulation.materialEmission[0]=HEAPF32[param>>2];GLEmulation.materialEmission[1]=HEAPF32[param+4>>2];GLEmulation.materialEmission[2]=HEAPF32[param+8>>2];GLEmulation.materialEmission[3]=HEAPF32[param+12>>2]}else if(pname==5634){var _r=HEAPF32[param>>2],_g=HEAPF32[param+4>>2],_b=HEAPF32[param+8>>2],_a=HEAPF32[param+12>>2];GLEmulation.materialAmbient[0]=_r;GLEmulation.materialAmbient[1]=_g;GLEmulation.materialAmbient[2]=_b;GLEmulation.materialAmbient[3]=_a;GLEmulation.materialDiffuse[0]=_r;GLEmulation.materialDiffuse[1]=_g;GLEmulation.materialDiffuse[2]=_b;GLEmulation.materialDiffuse[3]=_a}else{0}};var _emscripten_glMaterialfv=',
    ),
    (
        'glNormal3f outside begin/end',
        'var _glNormal3f=(x,y,z)=>{GLImmediate.vertexData[GLImmediate.vertexCounter++]=x;',
        'var _glNormal3f=(x,y,z)=>{if(GLImmediate.mode<0){GLEmulation.__curNormal=[x,y,z];return}GLImmediate.vertexData[GLImmediate.vertexCounter++]=x;',
        # detect stops BEFORE the point where the growable-normal patch inserts
        # __grow(), so that later patch cannot break this one's detection
        'var _glNormal3f=(x,y,z)=>{if(GLImmediate.mode<0){GLEmulation.__curNormal=[x,y,z];return}',
    ),
    (
        'init immediate mode on context switch (FCWEBMCC)',
        'GLImmediate.init());GLEmulation.init();for(var i=0;i<32;++i)',
        'GLImmediate.init());(function(){var _mcc=GL.makeContextCurrent;GL.makeContextCurrent=function(ctx){var r=_mcc.call(GL,ctx);try{if(GL.currentContext&&typeof GLctx!=="undefined"&&GLctx){if(!GLImmediate.initted){Browser.useWebGL=true;GLImmediate.init()}if(!GL.currentContext.tempVertexBuffers1){GL.generateTempBuffers(true,GL.currentContext)}}}catch(e){}return r}})();/*FCWEBMCC*/GLEmulation.init();for(var i=0;i<32;++i)',
    ),
]


# ---- a begin/end batch may be larger than 2 MB -------------------------------------
#
# Importing an STL killed the page: "Cannot read properties of undefined (reading
# 'undefined')" out of getTempVertexBuffer <- Renderer.prepare <- flush <- glEnd.
# Measured on the live build with a 51,200-triangle mesh: ONE glBegin(GL_TRIANGLES)
# block of 153,600 vertices at stride 28 = 4,300,800 bytes, with the line-merge
# accumulator provably uninvolved (mode 4, merged 0, pending false).
#
# emscripten sizes the whole immediate path off GL.MAX_TEMP_BUFFER_SIZE = 2 MB:
#
#   * GLImmediate.tempData is Float32Array(2MB>>2). Vertex writes are
#     `vertexData[vertexCounter++] = x` with NO bounds check, and a JS typed array
#     DISCARDS an out-of-range store -- so past 524,288 floats the mesh is silently
#     truncated. That is the quieter half of this bug and the reason a crash guard
#     alone would not have been a fix.
#   * GL.generateTempBuffers only builds ring slots up to log2ceil(2MB) = 21, so
#     getTempVertexBuffer(4300800) reads tempVertexBuffers1[23] -> undefined, then
#     indexes it with an undefined counter. That is the crash.
#
# Why grow rather than switch meshes to VBOs: Coin's VBO path is disabled on wasm
# deliberately and with measurements recorded in patches/coin3d (a 626-solid STEP
# assembly stays responsive at 245 s in immediate mode and never became responsive
# within 600 s with VBOs, scene-build uploads 7.3 -> 36.7 MB). Immediate mode is the
# fast path here; it just has to stop lying about capacity.
#
# Growth doubles, is confined to the begin/end buffer (the glDrawArrays/glDrawElements
# paths point vertexData at a heap subarray -- never ours to reallocate), and stops at
# a ceiling so a runaway cannot take the tab out. Each writer reserves a whole vertex
# of headroom rather than its own component count, so the check is one compare.
GROWABLE_IMMEDIATE = [
    (
        'growable immediate vertex buffer',
        'GLImmediate.tempData=new Float32Array(GL.MAX_TEMP_BUFFER_SIZE>>2);GLImmediate.indexData=new Uint16Array(GL.MAX_TEMP_BUFFER_SIZE>>1);GLImmediate.vertexDataU8=new Uint8Array(GLImmediate.tempData.buffer);',
        # The replacement must NOT contain the anchor verbatim: apply() runs three passes,
        # and an anchor that survives its own replacement is re-inserted on every one of
        # them (this definition landed three times before the parentheses were added).
        'GLImmediate.tempData=new Float32Array(GL.MAX_TEMP_BUFFER_SIZE>>2);GLImmediate.indexData=new Uint16Array(GL.MAX_TEMP_BUFFER_SIZE>>1);GLImmediate.vertexDataU8=new Uint8Array((GLImmediate.tempData).buffer);'
        'GLImmediate.__growMax=268435456;'
        'GLImmediate.__grow=function(){'
        'var d=GLImmediate.vertexData;'
        'if(d!==GLImmediate.tempData)return;'
        'if(GLImmediate.vertexCounter+16<=d.length)return;'
        'var n=d.length*2;'
        'while(GLImmediate.vertexCounter+16>n&&n<GLImmediate.__growMax>>2)n*=2;'
        'if(n>GLImmediate.__growMax>>2)n=GLImmediate.__growMax>>2;'
        'if(n<=d.length)return;'
        'var g=new Float32Array(n);g.set(d);'
        'GLImmediate.tempData=GLImmediate.vertexData=g;'
        'GLImmediate.vertexDataU8=new Uint8Array(g.buffer);'
        'GLImmediate.__grew=(GLImmediate.__grew||0)+1};',
    ),
    (
        'growable immediate: glVertex2f',
        'var _glVertex2f=(x,y)=>{GLImmediate.vertexData',
        'var _glVertex2f=(x,y)=>{GLImmediate.__grow();GLImmediate.vertexData',
    ),
    (
        'growable immediate: glVertex3f',
        'var _glVertex3f=(x,y,z)=>{GLImmediate.vertexData',
        'var _glVertex3f=(x,y,z)=>{GLImmediate.__grow();GLImmediate.vertexData',
    ),
    (
        'growable immediate: glVertex4f',
        'var _glVertex4f=(x,y,z,w)=>{GLImmediate.vertexData',
        'var _glVertex4f=(x,y,z,w)=>{GLImmediate.__grow();GLImmediate.vertexData',
    ),
    (
        # glNormal3f's writer is created by the 'glNormal3f outside begin/end' patch
        # above, so this anchors on that patch's OUTPUT (also what a released artifact
        # contains) -- never on the fresh form.
        'growable immediate: glNormal3f',
        'GLEmulation.__curNormal=[x,y,z];return}GLImmediate.vertexData[GLImmediate.vertexCounter++]=x;',
        'GLEmulation.__curNormal=[x,y,z];return}GLImmediate.__grow();GLImmediate.vertexData[GLImmediate.vertexCounter++]=x;',
    ),
    (
        'growable immediate: glTexCoord2i',
        'var _glTexCoord2i=(u,v)=>{GLImmediate.vertexData',
        'var _glTexCoord2i=(u,v)=>{GLImmediate.__grow();GLImmediate.vertexData',
    ),
    (
        # glColor4f writes PACKED BYTES through vertexDataU8, a view on the same buffer,
        # so it advances vertexCounter too and must reserve headroom like the rest --
        # and the view has to be rebuilt after a reallocation, which __grow does.
        'growable immediate: glColor4f',
        'if(GLImmediate.mode>=0){var start=GLImmediate.vertexCounter<<2;GLImmediate.vertexDataU8[start+0]=r*255;',
        'if(GLImmediate.mode>=0){GLImmediate.__grow();var start=GLImmediate.vertexCounter<<2;GLImmediate.vertexDataU8[start+0]=r*255;',
    ),
    (
        # The GPU-side ring only has slots for sizes up to MAX_TEMP_BUFFER_SIZE. Give an
        # oversize request its own single-slot ring: one buffer per size class, reused
        # every frame, instead of 64 multi-megabyte buffers or an undefined dereference.
        'oversize temp vertex buffer ring',
        'getTempVertexBuffer:sizeBytes=>{var idx=GL.log2ceilLookup(sizeBytes);var ringbuffer=GL.currentContext.tempVertexBuffers1[idx];',
        'getTempVertexBuffer:sizeBytes=>{var idx=GL.log2ceilLookup(sizeBytes);'
        'if(!GL.currentContext.tempVertexBuffers1[idx]){GL.currentContext.tempVertexBuffers1[idx]=[null];GL.currentContext.tempVertexBufferCounters1[idx]=0}'
        'else if(GL.currentContext.tempVertexBuffers1[idx].length===1){GL.currentContext.tempVertexBufferCounters1[idx]=0}'
        'var ringbuffer=GL.currentContext.tempVertexBuffers1[idx];',
    ),
]
PATCHES += GROWABLE_IMMEDIATE


# ---- polygon mode: Flat Lines drew the mesh as solid black --------------------------
#
# An unselected STL rendered nearly black while the same mesh under the selection
# highlight looked fine. Snooping the uniforms at the 21,600-vertex draws showed the
# mesh drawn TWICE per frame: once lit with the correct grey (diffuse 0.969), then the
# same triangles again with diffuse (0,0,0) -- the "Flat Lines" wireframe overlay.
# Coin renders that overlay by re-emitting the triangles under
# glPolygonMode(GL_FRONT_AND_BACK, GL_LINE) (SoGLDrawStyleElement.cpp:116); emscripten
# implements _glPolygonMode as ()=>{}  -- so the "wireframe" rasterised as filled black
# triangles on top of the shaded mesh. Same for POINT mode.
#
# Fix, two tiers:
#   * where the browser has the real WEBGL_polygon_mode extension (emscripten already
#     carries the binding as glPolygonModeWEBGL), forward to it -- true wireframe,
#     desktop parity;
#   * otherwise remember the requested mode and have GLImmediate.flush drop
#     triangle-family draws while it is LINE/POINT. The overlay simply doesn't appear;
#     the mesh underneath stays correctly shaded. Line/point primitives themselves
#     (real edges, vertices) are unaffected -- only triangles-in-line-mode are dropped.
# ponytail: no software triangle->line conversion; if wireframe-everywhere ever
# matters, that is the upgrade path.
# The installer is folded into the polygon-mode patch below (both are new in the same
# release cycle): anchoring a separate patch on the FCWEBMCC marker would sit inside
# that patch's already-applied detection string and break re-application on an
# already-patched release artifact -- the freecad-web-dev #12 failure class.
_CTX_STATE_INSTALLER = (
    '(function(){var m2=GL.makeContextCurrent;'
    'var FV=["materialAmbient","materialDiffuse","materialSpecular","materialEmission","materialShininess","lightModelAmbient"];'
    'var LV=["lightAmbient","lightDiffuse","lightSpecular","lightPosition"];'
    'function snap(){var s={lm2:GLEmulation.lightModelTwoSide,le:GLEmulation.lightingEnabled,'
    'en:(GLEmulation.lightEnabled||[]).slice()};'
    'for(var i=0;i<FV.length;i++){var v=GLEmulation[FV[i]];s[FV[i]]=v?Array.from(v):null}'
    'for(var j=0;j<LV.length;j++){s[LV[j]]=(GLEmulation[LV[j]]||[]).map(function(a){return a?Array.from(a):a})}'
    'return s}'
    'function rest(s){GLEmulation.lightModelTwoSide=s.lm2;GLEmulation.lightingEnabled=s.le;'
    'if(GLEmulation.lightEnabled&&s.en)for(var k=0;k<s.en.length;k++)GLEmulation.lightEnabled[k]=s.en[k];'
    'for(var i=0;i<FV.length;i++){var v=GLEmulation[FV[i]];if(v&&s[FV[i]])v.set(s[FV[i]])}'
    'for(var j=0;j<LV.length;j++){var d=GLEmulation[LV[j]],x=s[LV[j]];'
    'if(d&&x)for(var m=0;m<x.length;m++){if(x[m]&&d[m])d[m].set(x[m]);else if(x[m])d[m]=new Float32Array(x[m])}}'
    'GLImmediate.currentRenderer=null}'
    'GL.makeContextCurrent=function(ctx){var prev=GL.currentContext;'
    'try{if(prev&&typeof GLEmulation!=="undefined"&&GLEmulation.lightEnabled)prev.__fcEmu=snap()}catch(e){}'
    'var r=m2.apply(GL,arguments);'
    'try{var c=GL.currentContext;if(c&&c!==prev&&c.__fcEmu&&typeof GLEmulation!=="undefined")rest(c.__fcEmu)}catch(e){}'
    'return r}})();'
)

POLYGON_MODE = [
    (
        'glPolygonMode records the mode (and uses WEBGL_polygon_mode when real)',
        'var _glPolygonMode=()=>{};',
        'var _glPolygonMode=(face,pmode)=>{GLEmulation.__polyMode=pmode;'
        'try{if(GLctx.webglPolygonMode)GLctx.webglPolygonMode.polygonModeWEBGL(face,pmode)}catch(e){}};'
        + _CTX_STATE_INSTALLER,
    ),
    (
        # Anchored on flush()'s DRAW TAIL, which no other patch rewrites -- the head is
        # owned by the lighting patch and inserting there broke its already-applied
        # detection. The replacement is restructured (numIndexes>0) so it does not
        # contain the anchor contiguously (3-pass re-insertion trap).
        'flush drops triangle draws in LINE/POINT polygon mode',
        'if(numIndexes){GLctx.drawElements(GLImmediate.mode,numIndexes,GLctx.UNSIGNED_SHORT,ptr)}'
        'else{GLctx.drawArrays(GLImmediate.mode,startIndex,numVertices)}',
        'if(!(GLEmulation.__polyMode===6913||GLEmulation.__polyMode===6912)'
        '||GLctx.webglPolygonMode||GLImmediate.mode<4||GLImmediate.mode>6){'
        'if(numIndexes>0){GLctx.drawElements(GLImmediate.mode,numIndexes,GLctx.UNSIGNED_SHORT,ptr)}'
        'else{GLctx.drawArrays(GLImmediate.mode,startIndex,numVertices)}}',
    ),
]
PATCHES += POLYGON_MODE


# ---- per-context material/light state ----------------------------------------------
#
# An unselected mesh rendered nearly black WHENEVER ANOTHER 3D VIEW EXISTED (lum 65
# with a second document open, 236 the moment it is closed -- measured both ways).
# The uniform snoop showed the mesh's own draw uploading diffuse (0,0,0,0.5): not its
# material, the OTHER view's last-sent line material.
#
# Mechanism: every 3D view is its own GL context, and Coin's lazy elements cache
# "what I last sent" PER CONTEXT -- but emscripten's GLEmulation keeps materials and
# lights in one GLOBAL singleton. View A uploads black into the global; view B's Coin
# correctly believes its grey is still current in ITS context and skips the resend;
# view B's next flush uploads A's black. Nothing is wrong in either view alone, which
# is why every single-document test passed.
#
# Fix: on the context switch we already hook (FCWEBMCC), snapshot the mutable
# lighting/material fields into the outgoing context and restore the incoming
# context's snapshot, so the global singleton always mirrors what Coin believes about
# the CURRENT context. currentRenderer is dropped because renderer selection keys on
# lighting state. Anchored AFTER the FCWEBMCC marker so this composes as a separate
# patch (rewriting the FCWEBMCC patch itself would break re-application on an
# already-patched release artifact -- the freecad-web-dev #12 failure).

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

# ---------------------------------------------------------------------------------------
# Make the nine no-ops COUNTABLE.
#
# The patches above turn each `throw"gl*: TODO"` into a bare `0`, which was the right call
# (a throw unwinds through Coin's render traversal and takes the viewport with it) -- but a
# bare 0 is unmeasurable, and these have been silently doing nothing for the whole life of
# the build. glMaterialfv and glLightfv are how Coin sets material colour and lighting, so
# "no-op" plausibly means "shading differs from desktop": an unmeasured parity claim in a
# project whose target is 1:1 with desktop FreeCAD.
#
# These entries match the ALREADY-SUBSTITUTED form, in context. That matters: the shipped
# FreeCAD.js in the GitHub Release was patched before publication, so the throw text is long
# gone and there is nothing for the table above to match. Anchoring on the surrounding code
# instead makes the instrumentation deployable without a ~2 h relink. Each anchor was
# verified UNIQUE against the deployed FreeCAD.js before being written down -- a bare `0`
# would be hopeless, since it occurs everywhere in minified JS.
#
# Applied leniently (see apply()): on a FRESH link the throws still exist, the table above
# handles them, and these will not match. Absence is expected there, not an error.
_COUNT = ('(globalThis.__fcglNoop=globalThis.__fcglNoop||{},'
          'globalThis.__fcglNoop.%s=(globalThis.__fcglNoop.%s||0)+1,0)')


def _count(name):
    return _COUNT % (name, name)


COUNTING_PATCHES = [
    ('count glLightModelf',
     'ghtModelTwoSide=param!=0?true:false}else{0}}',
     'ghtModelTwoSide=param!=0?true:false}else{%s}}' % _count('glLightModelf')),
    ('count glLightModelfv',
     'odelAmbient[3]=HEAPF32[param+12>>2]}else{0}}',
     'odelAmbient[3]=HEAPF32[param+12>>2]}else{%s}}' % _count('glLightModelfv')),
    ('count glLightfv',
     'GLEmulation.lightPosition[lightId])}else{0}}',
     'GLEmulation.lightPosition[lightId])}else{%s}}' % _count('glLightfv')),
    ('count glMaterialfv (face)',
     'if(face!=1028&&face!=1032){0}',
     'if(face!=1028&&face!=1032){%s}' % _count('glMaterialfv_face')),
    # NOT counted: the glMaterialfv pname fallback, i.e.
    #     'GLEmulation.materialDiffuse[3]=_a}else{0}}'
    # That `{0}` sits INSIDE the replacement text of the 'glMaterialfv: EMISSION and
    # AMBIENT_AND_DIFFUSE' patch above. Rewriting it makes that patch's own
    # already-applied detection fail, because the tool looks for its replacement verbatim --
    # so the next run reports "1 patch site(s) not found" and refuses, which is exactly what
    # happened on the first deploy attempt.
    #
    # Dropped rather than worked around: glMaterialfv is still counted by the face check
    # above, so nothing is lost from the inventory, and a counter is not worth weakening
    # the detection that protects 33 patches the viewport depends on.
    ('count glTexCoord4f',
     'var _glTexCoord4f=()=>{0}',
     'var _glTexCoord4f=()=>{%s}' % _count('glTexCoord4f')),
    ('count glTexGenfv',
     'var _glTexGenfv=(coord,pname,param)=>{0}',
     'var _glTexGenfv=(coord,pname,param)=>{%s}' % _count('glTexGenfv')),
    ('count glTexGeni',
     'var _glTexGeni=(coord,pname,param)=>{0}',
     'var _glTexGeni=(coord,pname,param)=>{%s}' % _count('glTexGeni')),
]


def apply(text, _passes=3, counting=True):
    """Return (patched_text, [status per patch]). Idempotent.

    Applied repeatedly to a fixpoint: some sites only appear once an earlier patch has
    run (the glMaterialfv extension matches text that the throw->no-op patch creates),
    and hard-coding a working order is a trap the next patch would fall into.
    """
    for _ in range(_passes - 1):
        text, st = _apply_once(text)
        if all(s != 'applied' for _, s in st):
            break
    text, st = _apply_once(text)

    # The counting instrumentation is applied LENIENTLY and reported separately.
    #
    # It anchors on the already-substituted `0` form, which exists only in an asset that has
    # been patched before (i.e. the shipped release). On a FRESH link the original throws are
    # still present, the main table converts them, and none of these will match -- absence
    # there is correct, not a failure, so it must not be able to fail a build.
    #
    # Still strict about ambiguity: a replacement is skipped unless its anchor occurs
    # EXACTLY ONCE. Every anchor was verified unique against the deployed FreeCAD.js, and a
    # second occurrence would mean the emscripten output moved and the anchor is no longer
    # the thing it was derived from.
    if not counting:
        return text, st
    for name, old, new in COUNTING_PATCHES:
        if new in text:
            st.append((name, 'already applied'))
        elif text.count(old) == 1:
            text = text.replace(old, new, 1)
            st.append((name, 'applied'))
        elif text.count(old) == 0:
            st.append((name, 'n/a (unpatched source)'))
        else:
            st.append((name, 'SKIPPED - anchor not unique (%d)' % text.count(old)))
    return text, st


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
# GROWABLE_HEAP_F32()[x>>2] instead of HEAPF32[x>>2], nine throw patches reported
# "already applied", and the file still threw from nine GL entry points. A throw inside a
# GL call unwinds through Coin and takes the viewport with it.
#
# (This used to say the index became x>>>2>>>0. It does not: measured against a real
# growable build, only the accessor name changes. The wrong detail made the fix look
# bigger than it is -- 27 anchors to re-derive rather than one rule to apply.)
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
    # Every vertex writer must reserve headroom before it stores. A missing guard is not
    # visible as an error: the typed array discards the out-of-range write and the mesh
    # comes out truncated, so count the call sites rather than trust the per-patch status.
    ngrow = text.count('__grow=function')
    if ngrow != 1:
        bad.append(('growable immediate vertex buffer',
                    'expected exactly 1 definition, found %d (0 = absent, >1 = anchor '
                    'survived its own replacement and was re-inserted per pass)' % ngrow,
                    ngrow))
    else:
        n = text.count('GLImmediate.__grow()')
        if n != 6:
            bad.append(('growable immediate guards', 'expected 6 vertex-writer guards, found %d' % n, n))
    if 'tempVertexBuffers1[idx]=[null]' not in text:
        bad.append(('oversize temp vertex buffer ring', 'absent -- an oversize batch dereferences undefined', 1))
    if text.count('__polyMode') < 2:
        bad.append(('polygon mode', 'absent -- Flat Lines overlays draw as solid black triangles', 1))
    # A growable build is no longer rejected: _apply_once derives the growable form of each
    # anchor mechanically (see `growable`). The invariant that mattered is the one above --
    # none of the nine throw sites may survive -- and it holds for either form, because
    # those anchors are throw strings and contain no heap access at all.
    return bad


# With ALLOW_MEMORY_GROWTH the heap can move, so emscripten stops emitting a captured
# typed-array view and calls an accessor instead:
#
#     HEAPF32[param>>2]        ->    GROWABLE_HEAP_F32()[param>>2]
#
# Only the accessor name changes; the index expression is untouched. Measured against a
# real growable build of this application: 738 such accessors, eight names, and ZERO
# occurrences of the `>>>2>>>0` form this file used to claim.
#
# This matters because the anchors below are literal strings. Against a growable build
# they simply stop matching, and every throw-removal patch then falls through to the
# "already applied" arm -- whose marker is the literal `0`, which occurs everywhere in
# minified JS. Nine GL sites reported success while still throwing, and a throw inside a
# GL call unwinds through Coin and takes the viewport with it. That is what made the 4 GB
# build look impossible.
#
# Deriving the growable form mechanically is better than re-deriving 27 anchors by hand:
# there is one rule, it is checked by the postconditions either way, and a future
# emscripten that renames an accessor breaks loudly rather than silently.
_GROWABLE_HEAPS = {'8': 'I8', 'U8': 'U8', '16': 'I16', 'U16': 'U16',
                   '32': 'I32', 'U32': 'U32', 'F32': 'F32', 'F64': 'F64'}


def growable(s):
    """Rewrite HEAPF32[x>>2] as GROWABLE_HEAP_F32()[x>>2], for every heap type."""
    return re.sub(r'HEAP(F32|F64|U8|U16|U32|8|16|32)\[',
                  lambda m: 'GROWABLE_HEAP_%s()[' % _GROWABLE_HEAPS[m.group(1)], s)


# A growable build does not just rename the heap accessors. Measured by diffing a real
# ALLOW_MEMORY_GROWTH link against the 2 GB one, at the two sites that broke run
# 33004112792 ("glMaterialfv: EMISSION and AMBIENT_AND_DIFFUSE" and "line batching drain:
# glDrawElements", both NOT FOUND):
#
#   1. HEAPF32[i]            ->  GROWABLE_HEAP_F32()[i]        (already handled)
#   2. [param>>2]            ->  [param>>>2>>>0]               unsigned-safe indexing
#   3. var _f=(a,b)=>{...};  ->  function _f(a,b){...}         and the ";" goes with it
#   4. a pointer argument gains a coercion prologue:
#          function _glDrawElements(mode,count,type,indices,start,end){indices>>>=0;if(...
#
# Note on (2): PLAN-AFTER-RELEASE claimed there were "zero >>>2>>>0 forms" and that the
# comment saying otherwise was wrong. The comment was right. The plan was written against a
# grep of the wrong file and that mistake cost a 90-minute link.
#
# (4) is why this cannot be a string transform. The prologue is emitted per pointer
# argument, it is not derivable from the anchor, and DROPPING it would silently remove the
# coercion that makes the pointer valid past 2 GB -- which is the entire point of the build.
# So the growable form is matched as a regex that CAPTURES the prologue, and the
# replacement puts it back.
_PROLOGUE = r'((?:[A-Za-z_$][\w$]*>>>=0;)*)'
_FN_HEAD = re.compile(r'var (_' + r'\w+)=' + r'\(([^)]*)' + r'\)=>' + r'\{')


def _growable_regex(lit):
    """A pattern matching how a growable build emits this literal anchor.

    Returns (compiled_pattern, prologue_group_or_None). The group is 1 when the anchor
    began with a function head, because only then can a prologue appear inside it.
    """
    s = growable(lit)
    m = _FN_HEAD.match(s)
    if m:
        fn, args = m.group(1), m.group(2)
        head = ('(?:var ' + re.escape(fn) + '=' + re.escape('(' + args + ')') + '=>'
                + '|function ' + re.escape(fn) + re.escape('(' + args + ')') + ')'
                + re.escape('{') + _PROLOGUE)
        rest, group = s[m.end():], 1
    else:
        head, rest, group = '', s, None
    body = re.escape(rest)
    # >>2]  may be  >>>2>>>0]
    # In the escaped pattern, '>>2]' appears as '>>2\\]'. Relax it to accept
    # either that or the unsigned-safe '>>>2>>>0]'.
    body = re.sub(r'>>(\d)\\\]',
                  r'>>>?\1(?:>>>0)?\\]', body)
    # a converted function no longer needs its trailing semicolon
    body = body.replace(re.escape('};'), re.escape('}') + ';?')
    return re.compile(head + body), group


def _growable_replacement(new_lit, prologue):
    """The replacement, written the way a growable build writes it."""
    s = growable(new_lit)
    m = _FN_HEAD.match(s)
    if m:
        s = ('function ' + m.group(1) + '(' + m.group(2) + '){' + prologue + s[m.end():])
    # emit the unsigned-safe index form so the file stays internally consistent
    s = re.sub(r'(GROWABLE_HEAP_\w+\(\)\[[^]]*?)>>(\d+)]',
               r'\1>>>\2>>>0]', s)
    return s


def _apply_once(text):
    status = []
    # Only pay for the transform on a build that needs it.
    is_growable = 'GROWABLE_HEAP_' in text
    for entry in PATCHES:
        name, old, new = entry[0], entry[1], entry[2]
        # a 4th field is the text that proves the fix is in effect, for when a
        # LATER patch rewrites the surroundings so `new` no longer appears whole
        marker = entry[3] if len(entry) > 3 else new
        if is_growable and old not in text:
            old, new, marker = growable(old), growable(new), growable(marker)
        # Check for the UNPATCHED site first. Testing "is the replacement present"
        # first would misfire for short replacements -- "0;" occurs throughout
        # minified JS -- and silently skip a patch that was never applied.
        if old in text:
            text = text.replace(old, new, 1)
            status.append((name, 'applied'))
            continue
        if marker in text:
            status.append((name, 'already applied'))
            continue
        # Still nothing, and this is a growable build: the emission differs in ways a
        # string transform cannot express -- see _growable_regex.
        if is_growable:
            pat, grp = _growable_regex(entry[1])
            m = pat.search(text)
            if m:
                repl = _growable_replacement(entry[2], m.group(grp) if grp else '')
                text = text[:m.start()] + repl + text[m.end():]
                status.append((name, 'applied (growable form)'))
                continue
            mpat, _ = _growable_regex(marker if len(entry) > 3 else entry[2])
            if mpat.search(text):
                status.append((name, 'already applied (growable form)'))
                continue
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
        # Print what the file ACTUALLY says near each missing site. "not found" on its own
        # is a message that costs an hour: the fix is always a small shape change in
        # emscripten's generated glue (>>2 vs >>>2>>>0, HEAPF32 vs GROWABLE_HEAP_F32()),
        # and it cannot be re-derived without seeing the real text.
        for name in missing:
            old_str = next(e[1] for e in PATCHES if e[0] == name)
            # Anchor on the longest identifier in the pattern; those survive minification.
            print('  --- %s ---' % name, file=sys.stderr)
            # Longest prefix of the pattern that IS in the file. That is the exact point of
            # divergence, which a loose identifier anchor is not: anchoring on
            # "GLEmulation.materialShininess" found its Float32Array initialiser hundreds of
            # kilobytes away from the glMaterialfv body the patch is about.
            lo, hi = 0, len(old_str)
            while lo < hi:
                mid = (lo + hi + 1) // 2
                if src.find(old_str[:mid]) >= 0:
                    lo = mid
                else:
                    hi = mid - 1
            if lo == 0:
                print('  not one character of that pattern appears in the file',
                      file=sys.stderr)
            else:
                at = src.find(old_str[:lo])
                print('  matches the first %d of %d chars, at offset %d'
                      % (lo, len(old_str), at), file=sys.stderr)
                print('  pattern then wants: %r' % old_str[lo:lo + 120], file=sys.stderr)
                print('  file actually has:  %r'
                      % src[at + lo:at + lo + 120].replace(chr(10), ' '), file=sys.stderr)
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
    # counting=False here on purpose. A counting patch legitimately rewrites part of an
    # EARLIER patch's output -- the glMaterialfv EMISSION replacement ends in the same
    # `...materialDiffuse[3]=_a}else{0}}` that the counter anchors on -- so the exact-match
    # assertion below would fail on a change that is entirely correct. The counters get
    # their own checks after.
    out, status = apply(src, counting=False)
    # after the fixpoint loop the final pass reports 'already applied'; what matters
    # is that no site was missed
    bad = [(n, st) for n, st in status if st == 'NOT FOUND']
    assert not bad, bad
    for e in PATCHES:
        name, old, new = e[0], e[1], e[2]
        assert new in out, name

    # idempotent: a second pass must change nothing
    out2, status2 = apply(out, counting=False)
    assert out2 == out, 'not idempotent'

    # a file missing every site must be reported, not silently "fixed"
    _, s3 = apply('function unrelated(){}', counting=False)
    assert all(st == 'NOT FOUND' for _, st in s3), s3

    # The counters must be inert where their anchors do not exist -- which is every fresh
    # link, since those still carry the original throws. Absence there is correct, and must
    # never be able to fail a build.
    _, s4 = apply('function unrelated(){}')
    cnt = [(n, st) for n, st in s4 if n.startswith('count ')]
    assert cnt and all(st == 'n/a (unpatched source)' for _, st in cnt), cnt

    # A counter must never anchor inside another patch's REPLACEMENT text. If it does, it
    # rewrites that patch's output, the already-applied check stops matching, and the next
    # run reports the patch as missing and refuses -- which is precisely how the first
    # deploy of these counters failed. Catch it here instead of on the box.
    for cname, cold, _cnew in COUNTING_PATCHES:
        for entry in PATCHES:          # some entries carry a 4th 'marker' field
            pname, pnew = entry[0], entry[2]
            assert cold not in pnew, (
                'counter %r anchors inside the replacement of %r -- it would break that '
                "patch's already-applied detection" % (cname, pname))

    # And where an anchor DOES exist they must apply exactly once, then be idempotent.
    fixture = ''.join(old for _, old, _ in COUNTING_PATCHES)
    c1, sc1 = apply(fixture)
    assert all(st == 'applied' for n, st in sc1 if n.startswith('count ')), sc1
    c2, _ = apply(c1)
    assert c2 == c1, 'counting patches not idempotent'

    # NOTE: patches whose replacement is just "0" cannot be distinguished as
    # "already applied" vs "site absent" by content alone -- "0" is everywhere in
    # minified JS. That is why apply() tests for the UNPATCHED site first; the
    # worst case is a cosmetic status, never a missed or double substitution.

    print('patch-freecad-js selftest OK (%d patches + %d counters)'
          % (len(PATCHES), len(COUNTING_PATCHES)))


if __name__ == '__main__':
    if len(sys.argv) == 2 and sys.argv[1] == '--selftest':
        selftest()
    else:
        sys.exit(main())
