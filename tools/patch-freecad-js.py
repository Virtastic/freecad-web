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

WASM64

A wasm64 glue indexes the heap by DIVISION rather than by shift: a pointer is a BigInt
there, and BigInt will not take >> with a Number operand, so emscripten divides instead.
Measured on emsdk 6.0.9 by linking the same fixed-function program with and without -m64
(.github/workflows/wasm64-probe.yml): >>1 becomes /2 and >>2 becomes /4 across
HEAPU16/HEAP32/HEAPU32/HEAPF32, 92 shift-indexes became 0, and the .wasm grew 12.7%.

Nothing else moves. Of the 48 anchors here only FOUR carry a heap index; the other 44 are
byte-identical between targets. Arithmetic such as GLImmediate.stride>>2 is untouched,
because that is a plain Number and not a pointer -- which is why this is a relaxation of
the existing anchors rather than a second table.

The growable mode below is now DEAD on any current link. emsdk 6.0.9 no longer emits the
GROWABLE_HEAP_*() accessor form at all: linking with ALLOW_MEMORY_GROWTH=1 produces the
growth machinery and zero accessors, on both targets. It is kept only for the shipped
3.1.70-era asset. The long-standing claim that growth invalidates this table -- recorded
in BUILD-WEH.md and once used to argue against a bigger heap -- no longer holds.

The tool still fails CLOSED. check_postconditions() asserts exact counts and zero
surviving _TODO_THROWS, so a glue this does not understand is a loud refusal rather than
a silently unpatched engine -- which matters, because an unpatched engine boots and then
throws out of nine GL entry points, unwinds through Coin's render traversal and takes the
viewport with it.
"""
import re
import sys
import pathlib

PATCHES = [
    (
        'glGetString returns its cached pointer as a BigInt',
        # LEGACY_GL_EMULATION replaces glGetString AFTER emscripten wrapped the real one
        # for wasm64. The wrapped original computes a Number, caches THAT, and converts
        # only on the way out:
        #     ...GL.stringCache[name_]=ret}return ret})();return BigInt(ret)
        # so the cache holds Numbers. The emulation's own early return hands that Number
        # straight back to wasm, where the import is declared i64:
        #     TypeError: Cannot convert 75079704 to a BigInt
        #         at QRhiGles2::create(QFlags<QRhi::Flag>)
        # The first call for a given name goes through the original and works; every
        # later one throws -- which is why boot survives and the app dies the moment
        # anything builds a second GL surface: opening a document (QuarterWidget) or
        # Edit > Preferences (the backing store's RHI).
        '_glGetString=_emscripten_glGetString=name_=>{'
        'if(GL.stringCache[name_])return GL.stringCache[name_];',
        '_glGetString=_emscripten_glGetString=name_=>{'
        'if(GL.stringCache[name_])return BigInt(GL.stringCache[name_]);',
    ),
    (
        'glShaderSource length array is GLint, not pointer-sized',
        # emscripten reads the `const GLint *length` argument of glShaderSource with the
        # POINTER stride and the POINTER width -- src/lib/libwebgl.js, GL.getSource:
        #     var len = length ? {{{ makeGetValue('length', 'i*' + POINTER_SIZE, '*') }}}
        # At wasm32 that is a 4-byte read with a 4-byte stride, which is exactly what an
        # array of GLint is, so it has always been right by accident. At wasm64 it becomes
        # an 8-byte read with an 8-byte stride over 4-byte elements: chunk 0 gets
        # len[0] | len[1] << 32, and the later chunks read past the end of the array.
        #
        # Qt is the caller that notices. QOpenGLShader::compileSourceCode (qtbase 6.11.2,
        # qopenglshaderprogram.cpp:659) hands the version directive, a #line directive and
        # the shader body over as three chunks with a QVarLengthArray<GLint> of lengths:
        #     glShaderSource(id, sourceChunks.size(), sourceChunks.data(),
        #                    sourceChunkLengths.data());
        # so every shader Qt builds arrives truncated:
        #     QOpenGLShader::compile(Fragment): ERROR: -1:-1: "" : Missing main()
        #     Fragment shader for blitShaderProg (MainFragmentShader &
        #     ImageSrcFragmentShader) failed to compile
        # and Qt dumps a "problematic source" that is the preamble, then #line 1, then
        # nothing. With no blit and no simple program the widget layer never reaches the
        # window: menus, docks and toolbars go black the moment a 3D view forces an
        # OpenGL surface, while the 3D view itself keeps drawing, because Coin is
        # fixed-function and compiles no shaders at all. That split is why every gate
        # stayed green -- they photograph the viewport, which is the half that works.
        #
        # The marker is the 4-byte stride, so a wasm32 glue, which already reads it that
        # way, reports "already applied" instead of a missing site.
        'var len=length?Number(HEAPU64[length+i*8>>3]):undefined;',
        'var len=length?HEAPU32[length+i*4>>2]:undefined;',
        'length+i*4',
    ),
    (
        # Shared sessions (see infra/session/): when the page joins a session it materializes
        # an EPHEMERAL home before main() and must stop pre-gui.js from mounting the visitor's
        # own IDBFS home over it. pre-gui.js is --pre-js, baked in at link time, so until the
        # next relink carries the same line natively this is a post-link patch like the rest.
        # The flag is a plain property the page sets on the Module config before qtLoad, so
        # it does not depend on preRun ordering (addOnPreRun unshifts: the pre-js runs FIRST).
        'session mode: skip the IDBFS home mount',
        'qs2.has("noidbfs")&&typeof IDBFS!=="undefined"',
        'qs2.has("noidbfs")&&!Module.fcwebSessionMode&&typeof IDBFS!=="undefined"',
    ),
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
    # A TEXTURE FROM ANOTHER CONTEXT IS NOT BOUND -- SKIP THE CALL RATHER THAN RAISE.
    #
    # Qt gives every 3D view its own WebGL context, and Qt's RHI compositor then binds
    # each QOpenGLWidget's texture from the WINDOW's context: every one of those binds is
    # a WebGL INVALID_OPERATION ('object does not belong to this context'), 17-71 per
    # document opened, attributed by stack on 2026-09-10 to QRhiGles2::bindCombinedSampler
    # and nothing else. That compose never presents anyway -- the page composites the
    # window itself -- so the bind failing changes nothing except the console. The page
    # already stamps every texture with the context that created it (__fcGl, the same
    # tag its compositor keys on), so a bind from a different context can simply return:
    # the previous binding stays, exactly as the refused call would have left it. The tag
    # is set in GL.genObject too, because a texture that is only ever a framebuffer
    # attachment never passes through an upload and would otherwise carry none.
    (
        'bindTexture: skip a texture from another context instead of raising',
        'var _emscripten_glBindTexture=(target,texture)=>{GLctx.bindTexture(target,GL.textures[texture])};',
        'var _emscripten_glBindTexture=(target,texture)=>{var __t=GL.textures[texture];'
        'if(__t&&__t.__fcGl&&__t.__fcGl!==GLctx){GL.__fcXBind=(GL.__fcXBind|0)+1;GLctx.__fcNoTex=true;return}'
        'GLctx.__fcNoTex=false;GLctx.bindTexture(target,__t)};',
    ),
    (
        'genObject: stamp every GL object with the context that created it',
        'genObject:(n,buffers,createFunction,objectTable)=>{for(var i=0;i<n;i++){var buffer=GLctx[createFunction]();var id=buffer&&GL.getNewId(objectTable);if(buffer){buffer.name=id;objectTable[id]=buffer}',
        'genObject:(n,buffers,createFunction,objectTable)=>{for(var i=0;i<n;i++){var buffer=GLctx[createFunction]();var id=buffer&&GL.getNewId(objectTable);if(buffer){buffer.name=id;buffer.__fcGl=GLctx;objectTable[id]=buffer}',
    ),
    # MIGRATION: build-20260911's link (commit 4b9de04) baked a useProgram guard that a later
    # measurement disproved (it never fired: GL.__fcXProg stayed 0 across every census). It
    # is inert but it is also a lie in the shipped glue; take it back out of any asset that
    # carries it. (The program tag stays: the context sweep in deleteContext uses it.)
    (
        'useProgram: remove the disproved cross-context guard',
        'var _emscripten_glUseProgram=program=>{program=GL.programs[program];'
        'if(program&&program.__fcGl&&program.__fcGl!==GLctx){GL.__fcXProg=(GL.__fcXProg|0)+1;GLctx.currentProgram=null;return}'
        'GLctx.useProgram(program);GLctx.currentProgram=program};',
        'var _emscripten_glUseProgram=program=>{program=GL.programs[program];GLctx.useProgram(program);GLctx.currentProgram=program};',
    ),
    (
        'createProgram: stamp the program with the context that created it',
        'var program=GLctx.createProgram();program.name=id;program.maxUniformLength=',
        'var program=GLctx.createProgram();program.name=id;program.__fcGl=GLctx;program.maxUniformLength=',
    ),
    (
        'createShader: stamp the shader with the context that created it',
        'GL.shaders[id]=GLctx.createShader(shaderType);return id}',
        'GL.shaders[id]=GLctx.createShader(shaderType);if(GL.shaders[id])GL.shaders[id].__fcGl=GLctx;return id}',
    ),
    # texParameter after a bind this glue refused: there is no texture on the target, so
    # the call would raise 'no texture bound to target'. Skip it while the last bind on
    # this context was a refused one; the next real bind clears the flag.
    (
        'texParameteri: no-op after a refused bind',
        'var _emscripten_glTexParameteri=(x0,x1,x2)=>GLctx.texParameteri(x0,x1,x2);',
        'var _emscripten_glTexParameteri=(x0,x1,x2)=>{if(GLctx.__fcNoTex)return;GLctx.texParameteri(x0,x1,x2)};',
    ),
    (
        'texParameterf: no-op after a refused bind',
        'var _emscripten_glTexParameterf=(x0,x1,x2)=>GLctx.texParameterf(x0,x1,x2);',
        'var _emscripten_glTexParameterf=(x0,x1,x2)=>{if(GLctx.__fcNoTex)return;GLctx.texParameterf(x0,x1,x2)};',
    ),
    # glTexEnvf(GL_TEXTURE_ENV, GL_TEXTURE_ENV_MODE, GL_MODULATE) IS DROPPED ON THE FLOOR.
    #
    # emscripten's hook_texEnvf handles only GL_RGB_SCALE / GL_ALPHA_SCALE; every other pname
    # hits `default:0`. GL allows the f variant for any enum-valued pname, and NaviCube.cpp
    # uses it: glTexEnvi(..., GL_REPLACE) then glTexEnvf(..., GL_MODULATE) -- so the cube's
    # label textures rendered in REPLACE, i.e. raw white glyphs instead of glyphs tinted with
    # the emphasis colour: near-invisible on a light face (measured 2026-09-11: interior 245
    # on a 247 face, and the mip filter made no difference). Route every pname that is not a
    # scale through hook_texEnvi, which knows all of them.
    (
        'hook_texEnvf: forward enum pnames to hook_texEnvi',
        'hook_texEnvf(target,pname,param){if(target!=GL_TEXTURE_ENV)return;var env=getCurTexUnit().env;switch(pname){case GL_RGB_SCALE:',
        'hook_texEnvf(target,pname,param){if(target!=GL_TEXTURE_ENV)return;'
        'if(pname!==GL_RGB_SCALE&&pname!==GL_ALPHA_SCALE){return GLImmediate.TexEnvJIT.hook_texEnvi(target,pname,param)}'
        'var env=getCurTexUnit().env;switch(pname){case GL_RGB_SCALE:',
    ),
    # QT 6.11 QUEUES EVERY DOM EVENT FOR ITS OWN EVENT LOOP TO DRAIN ON RESUME. That loop is
    # callback-driven here (main() has returned), so a queued pointerdown sat in
    # Module.qtSuspendResumeControl.pendingEvents (43 -> 51 entries, measured 2026-09-11)
    # and the browser turned the drag into HTML5 drag-and-drop: preventDefault only counts
    # while the DOM event is being dispatched. Deliver inline. The paint chain this leaves
    # starved (posted UpdateLater -> wake-up timer -> requestAnimationFrame) is driven from
    # the page instead: freecad-gui.html asks Qt to process posted events once per
    # animation frame while input is live (68 scene frames per 4 s drag, from 2-6).
    (
        'Qt 6.11: deliver DOM events inline instead of queueing them',
        'else{if(control.asyncifyEnabled){}else{Module.qtSendPendingEvents()}}};control.eventHandlers[index]=handler',
        'else{Module.qtSendPendingEvents()}};control.eventHandlers[index]=handler',
    ),
    # MIGRATION for an asset patched with the previous (wrong) mapping -- see the entry
    # below. Anchors on the old replacement text and rewrites it; on a fresh link the
    # primary entry produces the corrected text directly and this one reads as applied.
    (
        'glGet legacy fixed-function queries (migrate 2834/2850)',
        'if(name_===2834){ret=1029}else if(name_===2850){ret=6914}else if(name_===3377){ret=8}',
        'if(name_===2834){name_=33901}else if(name_===2850){name_=33902}else if(name_===2880){ret=6914}'
        'else if(name_===3377){ret=8}',
    ),
    (
        'glGet legacy fixed-function queries',
        'ret=name_==33307?3:0;break}if(ret===undefined){var result=GLctx.getParameter(name_);',
        'ret=name_==33307?3:0;break}if(ret===undefined){if(name_===2834){name_=33901}'
        'else if(name_===2850){name_=33902}else if(name_===2880){ret=6914}'
        'else if(name_===3377){ret=8}else if(name_===3121){ret=0}}if(ret===undefined){'
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
        # 4th field: the entry below rewrites the program bind inside this replacement.
        'flush(numProvidedIndexes,startIndex=0,ptr=0){try{if(typeof GLEmulation!=="undefined"&&GLImmediate.enabledClientAttributes){',
    ),
    # THE FORCED BIND MUST KEEP THE EMULATION'S OWN TRACKING HONEST.
    #
    # Qt 6.11 resolves a QOpenGLWidget's multisampled framebuffer with an RHI pass ON THE
    # WIDGET'S OWN CONTEXT -- the one Coin draws in -- and leaves its shader program bound;
    # the emulation records it as GL.currProgram. Coin's next fixed-function flush hits the
    # bind above, which puts the renderer program on the driver but left GL.currProgram
    # alone. The emulation's glUseProgram wrapper skips any request equal to GL.currProgram,
    # so Qt's next glUseProgram of the same program was swallowed and every uniform it set
    # landed on the renderer program: 'location is not from the associated program', 96-805
    # per session. Measured 2026-09-11 with a per-context event ring inside the glue:
    # em-use:62, fc-force-bind, em-use:65, fc-force-bind ... with the renderer program on the
    # driver at every failing uniform. Once the renderer program is bound the app program
    # is not current in any sense the emulation cares about: say so, and its own prepare /
    # cleanup and the next real glUseProgram all do the right thing.
    (
        'GLImmediate.flush: a forced renderer bind clears GL.currProgram',
        'if(renderer&&renderer.program){GLctx.useProgram(renderer.program)}',
        'if(renderer&&renderer.program){GLctx.useProgram(renderer.program);if(GL.currProgram){GL.currProgram=0;GLImmediate.currentRenderer=null}GLImmediate.fixedFunctionProgram=renderer.program}',
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
        'immediate renderer binds the app ARRAY_BUFFER before setting attributes',
        # prepare() computes which buffer the client attributes live in, and when the
        # application has one bound it takes that buffer -- but then never binds it:
        #
        #   if (!GLctx.currentArrayBufferBinding) { arrayBuffer = GL.getTempVertexBuffer(end) }
        #   else                                  { arrayBuffer = GLctx.currentArrayBufferBinding }
        #   if (!GLctx.currentArrayBufferBinding) { ...bindBuffer(ARRAY_BUFFER, arrayBuffer)... }
        #
        # The bind only happens on the client-array branch, so the VBO branch is trusting
        # that the REAL binding still equals the shadow variable. In this build it does not
        # have to: the immediate path binds its own temp vertex buffer, and 'glEnd clears a
        # stale ARRAY_BUFFER binding' below unbinds behind it. vertexAttribPointer then
        # attaches the offsets to whatever buffer happens to be current, which is how
        # SoBrepFaceSet's VBO path "executes but rasterizes NOTHING" -- the comment its C++
        # carries, and the reason every Part solid is forced onto immediate mode instead.
        #
        # Costs one bindBuffer per draw on a path that is currently unreachable, and makes
        # the VBO branch state its own precondition instead of inheriting it.
        'else{arrayBuffer=GLctx.currentArrayBufferBinding}',
        'else{arrayBuffer=GLctx.currentArrayBufferBinding;'
        'GLctx.bindBuffer(GLctx.ARRAY_BUFFER,GL.buffers[arrayBuffer]||null);'
        'GLImmediate.lastArrayBuffer=arrayBuffer;}',
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
        # 4th field: the POINT guard below rewrites the forwarding condition inside this
        # replacement, so `new` stops appearing whole once both are in -- the same 3-pass
        # re-insertion trap the flush patch documents. Without this the patch flips from
        # 'already applied' to NOT FOUND, apply() errors, and the tool refuses to write
        # ANY patch, silently taking the other 32 with it. Detect on the assignment, which
        # both forms contain and nothing rewrites.
        'GLEmulation.__polyMode=pmode',
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
        # 4th field: the index-type patch below rewrites the drawElements call inside this
        # replacement, so `new` no longer appears whole once both are in. Detect on the
        # mode test instead, which nothing else touches.
        'if(!(GLEmulation.__polyMode===6913||GLEmulation.__polyMode===6912)'
        '||GLctx.webglPolygonMode||GLImmediate.mode<4||GLImmediate.mode>6){',
    ),
]
# ---- polygon mode: do not hand GL_POINT to an extension that rejects it --------------
#
# WEBGL_polygon_mode accepts FILL (6914) and LINE (6913) only, on FRONT_AND_BACK (1032).
# Coin also asks for POINT (6912) -- the Points draw style -- and the extension answers
# GL_INVALID_ENUM "glPolygonModeANGLE: Invalid polygon mode" for every single call.
# Reported from the dev console opening a sample file: 255 of them, then "too many
# errors, no more errors will be reported for this context", which silences the console
# for anything genuinely wrong afterwards.
#
# The surrounding try/catch cannot help: a WebGL error is not a JS exception, it sets the
# context error state and logs.
#
# Behaviour is otherwise unchanged. __polyMode is still recorded, so the flush patch above
# keeps its existing handling. POINT mode still rasterises filled where the extension is
# present (flush only drops triangle draws when the extension is ABSENT) -- that is
# pre-existing and not what this fixes; this only stops the error storm.
#
# Its own entry rather than an edit to the patch above, because changing that patch's
# replacement would leave an already-patched release artifact matching neither its anchor
# nor its new text, and the fix would never reach the asset that actually ships.
POLYGON_MODE += [
    (
        'glPolygonMode does not forward POINT to WEBGL_polygon_mode',
        'var _glPolygonMode=(face,pmode)=>{GLEmulation.__polyMode=pmode;try{if(GLctx.webglPolygonMode)GLctx.webglPolygonMode.polygonModeWEBGL(face,pmode)}catch(e){}};',
        # A fresh link goes straight to the lazy-extension form (the entry below migrates
        # assets that carry the intermediate one).
        'var _glPolygonMode=(face,pmode)=>{GLEmulation.__polyMode=pmode;try{if(face===1032&&(pmode===6913||pmode===6914)&&(pmode!==6914||GLctx.__fcPolyUsed)){'
        'if(GLctx.webglPolygonMode===undefined){GLctx.webglPolygonMode=GLctx.getExtension("WEBGL_polygon_mode")}'
        'if(GLctx.webglPolygonMode){GLctx.__fcPolyUsed=true;GLctx.webglPolygonMode.polygonModeWEBGL(face,pmode)}}}catch(e){}};',
        # 4th field: the lazy-extension entry below rewrites this condition.
        'var _glPolygonMode=(face,pmode)=>{GLEmulation.__polyMode=pmode;try{if(',
    ),
]

# MIGRATION: an asset patched with the previous POINT form (every link up to and including
# build-20260910) carries neither the anchor above nor its replacement. Rewrite that form in
# place so the deploy-time re-run and a rescued release both come out identical to a fresh
# link -- the tool fails closed on NOT FOUND, so without this it would write nothing.
POLYGON_MODE += [
    (
        'glPolygonMode: migrate the previous forwarding condition',
        '&&face===1032&&(pmode===6913||pmode===6914))GLctx.webglPolygonMode.polygonModeWEBGL(face,pmode)}catch(e){}};',
        '&&face===1032&&(pmode===6913||pmode===6914)&&(pmode!==6914||GLctx.__fcPolyUsed)){GLctx.__fcPolyUsed=true;GLctx.webglPolygonMode.polygonModeWEBGL(face,pmode)}}catch(e){}};',
        '(pmode!==6914||GLctx.__fcPolyUsed)){',
    ),
    # THE EXTENSION IS ENABLED ONLY WHEN WIREFRAME IS ACTUALLY ASKED FOR.
    #
    # emscripten enables every supported extension at context creation, and Chrome prints
    # 'this extension has very low support on mobile devices ... WEBGL_polygon_mode' once
    # per context for it -- two at boot and one per document opened, the only console
    # warning left after the 2026-09-11 census. Take it out of the eager set and fetch it
    # on the first LINE/POINT request; a user who never leaves FILL never sees the note.
    (
        'glPolygonMode: enable WEBGL_polygon_mode lazily',
        'try{if(GLctx.webglPolygonMode&&face===1032&&(pmode===6913||pmode===6914)&&(pmode!==6914||GLctx.__fcPolyUsed)){GLctx.__fcPolyUsed=true;GLctx.webglPolygonMode.polygonModeWEBGL(face,pmode)}}catch(e){}};',
        'try{if(face===1032&&(pmode===6913||pmode===6914)&&(pmode!==6914||GLctx.__fcPolyUsed)){'
        'if(GLctx.webglPolygonMode===undefined){GLctx.webglPolygonMode=GLctx.getExtension("WEBGL_polygon_mode")}'
        'if(GLctx.webglPolygonMode){GLctx.__fcPolyUsed=true;GLctx.webglPolygonMode.polygonModeWEBGL(face,pmode)}}}catch(e){}};',
    ),
    (
        'context init: WEBGL_polygon_mode is not enabled eagerly',
        'webgl_enable_EXT_clip_control(GLctx);webgl_enable_WEBGL_polygon_mode(GLctx);webgl_enable_ANGLE_instanced_arrays(GLctx);',
        'webgl_enable_EXT_clip_control(GLctx);webgl_enable_ANGLE_instanced_arrays(GLctx);',
    ),
    (
        'supported-extension list: WEBGL_polygon_mode is not enabled by the generic loop',
        '"WEBGL_multi_draw","WEBGL_polygon_mode"];return ctx.getSupportedExtensions()',
        '"WEBGL_multi_draw"];return ctx.getSupportedExtensions()',
    ),
]

# THE EMULATION'S PROGRAM TRACKING IS GLOBAL; THE APP HAS MANY CONTEXTS.
#
# LEGACY_GL_EMULATION wraps glUseProgram as `if (GL.currProgram != program) {...real call}`
# and binds its own fixed-function renderer program natively, tracked by
# GLImmediate.fixedFunctionProgram -- both plain globals, written from whichever context
# happens to be current. Qt-wasm gives the window one context and every 3D view its own,
# so a fixed-function flush on a view context leaves the globals describing THAT context,
# and the next glUseProgram Qt's RHI issues on the window is compared against a value that
# was never true there. Measured 2026-09-11 from inside the glue with a per-context event
# ring: emscripten requested program 81, 78, 81, 78 ... on the window context while the
# driver had a renderer program bound before every one of them -- 224-805 'location is
# not from the associated program' per session, the last of the console noise. Save and
# restore both per context in the same makeContextCurrent hook that already carries the
# lighting state across; a context seen for the first time starts at 0, which is true.
POLYGON_MODE += [
    (
        'makeContextCurrent: GL.currProgram and fixedFunctionProgram are per context',
        'prev.__fcEmu=snap()}catch(e){}var r=m2.apply(GL,arguments);',
        'prev.__fcEmu=snap()}catch(e){}'
        'try{if(prev){prev.__fcCurProg=GL.currProgram;prev.__fcFFP=GLImmediate.fixedFunctionProgram}}catch(e){}'
        'var r=m2.apply(GL,arguments);'
        'try{var c2=GL.currentContext;if(c2&&c2!==prev){GL.currProgram=c2.__fcCurProg||0;GLImmediate.fixedFunctionProgram=c2.__fcFFP||0;GLImmediate.currentRenderer=null}}catch(e){}',
    ),
]

# A DRAW UNDER THE APP'S OWN SHADER MUST NOT BE ROUTED THROUGH THE FIXED-FUNCTION PATH BY
# CLIENT-ARRAY STATE IT NEVER TOUCHED.
#
# emscripten sends glDrawArrays/glDrawElements through GLImmediate whenever any client array
# is enabled -- state that is global here and that Coin (and upstream NaviCube, fixed in
# freecad.patch) leaves enabled. Qt's RHI then draws its sample-resolve quad with its own
# program bound and generic attributes in a VAO, and the emulation rebuilt it as a fixed-
# function draw: renderer program bound over Qt's, Qt's uniforms failing from then on.
# The tell is that the enabled client arrays predate the glUseProgram: remember how many
# were enabled when a program was bound, clear that memory on the next glEnable/
# DisableClientState (fresh fixed-function intent), and while it stands, draw directly.
POLYGON_MODE += [
    (
        'glUseProgram: remember the client arrays enabled before an app program bind',
        'if(GL.currProgram!=program){GLImmediate.currentRenderer=null;GL.currProgram=program;GLImmediate.fixedFunctionProgram=0;orig_glUseProgram(program)}',
        'if(GL.currProgram!=program){GLImmediate.currentRenderer=null;GL.currProgram=program;GLImmediate.fixedFunctionProgram=0;'
        'GLImmediate.__fcStaleECA=program?GLImmediate.totalEnabledClientAttributes:0;orig_glUseProgram(program)}',
    ),
    (
        'glEnableClientState: fresh fixed-function intent',
        'var _glEnableClientState=_emscripten_glEnableClientState;',
        'var _glEnableClientState=_emscripten_glEnableClientState=(function(f){return cap=>{GLImmediate.__fcStaleECA=0;return f(cap)}})(_emscripten_glEnableClientState);',
    ),
    (
        'glDisableClientState: fresh fixed-function intent',
        'var _glDisableClientState=_emscripten_glDisableClientState;',
        'var _glDisableClientState=_emscripten_glDisableClientState=(function(f){return cap=>{GLImmediate.__fcStaleECA=0;return f(cap)}})(_emscripten_glDisableClientState);',
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
        if 'growMemViews()' in text:
            old, new = emsdk6_count(name, old, new)
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


# TRIANGLE strips and fans are NOT batched here, and two attempts to add them FAILED.
#
# Expanding them into independent triangles the way lines are expanded is arithmetically
# straightforward and measurably faster -- ArchDetail went 2437 -> 1064 draws/frame and
# 700 -> 565 ms -- but it turns SOLID FACES INTO WIREFRAME on the immediate path: 57-87%
# of pixels differ from the same document rendered without it. ?vbofaces=1 hides that
# entirely, because the VBO face path does not go through immediate mode, and that is how
# it shipped once (3480556, reverted in 73b7693) -- every check in the repo was running
# with faces on by default at the time.
#
# The second attempt guessed at the vertex LAYOUT: __mrgCmp compares matrices and material
# but never the attribute set, while __flushMerged draws the whole batch with the LAST
# snapshot's -- harmless for lines, which all carry the same attributes, wrong for
# triangles, where some primitives have normals and some do not. Refusing to merge across
# a stride or attribute-set change did NOT fix it, so that is not the mechanism either.
#
# Whoever tries again: run the ?vbofaces=0 A/B FIRST (scratchpad/faces-ab.py) and find out
# WHY the faces vanish before changing anything -- both attempts reasoned from a plausible
# mechanism instead, and both were wrong. Worth knowing too that these files are no longer
# call-bound: what remains is ~25-60 ms fixed plus ~50-85 ms of per-pixel rasterisation at
# 1280x720, and fewer draw calls touches neither.
#
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
NEW_END_MERGE = 'GLImmediate.__mrgN=0;GLImmediate.__mrgPend=false;GLImmediate.__mrgPrevVC=0;GLImmediate.__mrgSnap=null;GLImmediate.__mrgOn=!/[?&]nomerge=1/.test(location.search);globalThis.__GLI=GLImmediate;GLImmediate.__mrgPrev=new Float64Array(128);GLImmediate.__mrgHave=false;GLImmediate.__mrgPrep=function(){var S=GLImmediate.stride>>2;if(!S)return false;var base=GLImmediate.__mrgPrevVC,n=(GLImmediate.vertexCounter-base)/S;if(n<2||n!==(n|0))return false;if(GLImmediate.mode===1)return (n&1)===0;if(GLImmediate.mode!==3)return false;if(n===2)return true;var need=base+2*(n-1)*S,vc=GLImmediate.vertexCounter;GLImmediate.vertexCounter=need;GLImmediate.__grow();GLImmediate.vertexCounter=vc;var v=GLImmediate.vertexData;if(!v||v.length<need)return false;for(var i=n-2;i>=0;i--){var s=base+i*S,d0=base+2*i*S,d1=d0+S,k;for(k=S-1;k>=0;k--)v[d1+k]=v[s+S+k];for(k=S-1;k>=0;k--)v[d0+k]=v[s+k];}GLImmediate.vertexCounter=need;return true;};GLImmediate.__mrgCmp=function(commit){var E=(typeof GLEmulation!=="undefined")?GLEmulation:null;var a=GLImmediate.__mrgPrev,n=0,same=GLImmediate.__mrgHave,v,i,j;function put(x){x=+x||0;if(a[n]!==x){same=false;if(commit)a[n]=x}n++}put(GLImmediate.matrixVersion[0]);put(GLImmediate.matrixVersion[1]);for(i=0;i<2;i++){v=GLImmediate.matrix[i];if(v)for(j=0;j<16;j++)put(v[j])}if(E){put(E.lightingEnabled?1:0);put(E.lightModelTwoSide);var ks=["materialAmbient","materialDiffuse","materialEmission","materialSpecular","materialShininess","lightModelAmbient"];for(i=0;i<ks.length;i++){v=E[ks[i]];if(v)for(j=0;j<v.length;j++)put(v[j])}if(E.lightEnabled)for(i=0;i<E.lightEnabled.length;i++)put(E.lightEnabled[i]?1:0)}if(commit)GLImmediate.__mrgHave=true;return same};GLImmediate.__mf=function(){if(GLImmediate.__mrgPend)GLImmediate.__flushMerged()};GLImmediate.__flushMerged=()=>{if(!GLImmediate.__mrgPend)return;var S=GLImmediate.__mrgSnap;GLImmediate.__mrgPend=false;GLImmediate.__mrgN=0;GLImmediate.__mrgSnap=null;GLImmediate.__mrgHave=false;var kCA=GLImmediate.clientAttributes,kECA=GLImmediate.enabledClientAttributes,kRC=GLImmediate.rendererComponents,kMode=GLImmediate.mode,kStride=GLImmediate.stride;GLImmediate.clientAttributes=S.ca;GLImmediate.enabledClientAttributes=S.eca;GLImmediate.rendererComponents=S.rc;GLImmediate.stride=S.stride;GLImmediate.currentRenderer=null;GLImmediate.modifiedClientAttributes=true;GLImmediate.firstVertex=0;GLImmediate.lastVertex=GLImmediate.vertexCounter/(GLImmediate.stride>>2);GLImmediate.mode=1;GLImmediate.flush();GLImmediate.disableBeginEndClientAttributes();GLImmediate.clientAttributes=kCA;GLImmediate.enabledClientAttributes=kECA;GLImmediate.rendererComponents=kRC;GLImmediate.stride=kStride;GLImmediate.mode=kMode;GLImmediate.currentRenderer=null;GLImmediate.modifiedClientAttributes=true;GLImmediate.vertexCounter=0;GLImmediate.__mrgPrevVC=0};var _glEnd=()=>{GLImmediate.prepareClientAttributes(GLImmediate.rendererComponents[GLImmediate.VERTEX],true);GLImmediate.firstVertex=0;GLImmediate.lastVertex=GLImmediate.vertexCounter/(GLImmediate.stride>>2);if(GLctx.currentArrayBufferBinding){GLctx.bindBuffer(GLctx.ARRAY_BUFFER,null);GLctx.currentArrayBufferBinding=null;}if(GLImmediate.__mrgOn&&(GLImmediate.mode===3||GLImmediate.mode===1)&&GLImmediate.stride&&!(typeof GLEmulation!=="undefined"&&GLEmulation.lightingEnabled)&&GLImmediate.__mrgPrep()){GLImmediate.__mrgPend=true;GLImmediate.__mrgN++;GLImmediate.__mrgSnap={ca:GLImmediate.clientAttributes,eca:GLImmediate.enabledClientAttributes,rc:GLImmediate.rendererComponents,stride:GLImmediate.stride};GLImmediate.__mrgCmp(true);GLImmediate.disableBeginEndClientAttributes();GLImmediate.mode=-1;GLImmediate.enabledClientAttributes=GLImmediate.enabledClientAttributes_preBegin;GLImmediate.clientAttributes=GLImmediate.clientAttributes_preBegin;GLImmediate.currentRenderer=null;GLImmediate.modifiedClientAttributes=true;return;}if(GLImmediate.__mrgPend){var __m=GLImmediate.mode,__vc=GLImmediate.vertexCounter,__base=GLImmediate.__mrgPrevVC;GLImmediate.vertexCounter=__base;GLImmediate.__flushMerged();if(__vc>__base){GLImmediate.vertexData.copyWithin(0,__base,__vc);}GLImmediate.vertexCounter=__vc-__base;GLImmediate.mode=__m;GLImmediate.firstVertex=0;GLImmediate.lastVertex=GLImmediate.vertexCounter/(GLImmediate.stride>>2);}GLImmediate.flush();GLImmediate.disableBeginEndClientAttributes();GLImmediate.mode=-1;GLImmediate.enabledClientAttributes=GLImmediate.enabledClientAttributes_preBegin;GLImmediate.clientAttributes=GLImmediate.clientAttributes_preBegin;GLImmediate.currentRenderer=null;GLImmediate.modifiedClientAttributes=true}'
OLD_VC_MERGE = 'GLImmediate.mode=mode;GLImmediate.vertexCounter=0;'
NEW_VC_MERGE = 'GLImmediate.mode=mode;if(GLImmediate.__mrgPend&&(mode===3||mode===1)&&GLImmediate.__mrgSnap&&GLImmediate.__mrgCmp(false)){GLImmediate.__mrgPrevVC=GLImmediate.vertexCounter;}else{GLImmediate.__mf();GLImmediate.vertexCounter=0;GLImmediate.__mrgPrevVC=0;}'
DRAINS_MERGE = [('var _glDrawArrays=(mode,first,count)=>{if(GLImmediate.totalEnabledClientAttribu', 'var _glDrawArrays=(mode,first,count)=>{GLImmediate.__mf();if(GLImmediate.totalEnabledClientAttribu'), ('var _glDrawElements=(mode,count,type,indices,start,end)=>{if(GLImmediate.totalEnabledClientAttribu', 'var _glDrawElements=(mode,count,type,indices,start,end)=>{GLImmediate.__mf();if(GLImmediate.totalEnabledClientAttribu'), ('var _glEnableClientState=cap=>{var attrib=GLEmulation.getAttributeFromC', 'var _glEnableClientState=cap=>{GLImmediate.__mf();var attrib=GLEmulation.getAttributeFromC'), ('var _glDisableClientState=cap=>{var attrib=GLEmulation.getAttributeFromC', 'var _glDisableClientState=cap=>{GLImmediate.__mf();var attrib=GLEmulation.getAttributeFromC')]

MERGE_PATCHES = [
    ('immediate-mode line batching: glEnd defers', OLD_END_MERGE, NEW_END_MERGE),
    ('immediate-mode line batching: glBegin continues', OLD_VC_MERGE, NEW_VC_MERGE),
]
# 4th field: the stale-client-array entries below rewrite the fast-path condition that
# follows the drain, so `n` stops appearing whole on the fixpoint's later passes; detect
# the drain on its own prefix, up to and including the `if(` it drains before.
MERGE_PATCHES += [('line batching drain: ' + o.split('=')[0].replace('var _gl', 'gl'),
                   o, n, (n.split('if(')[0] + 'if(') if 'if(' in n else n) for o, n in DRAINS_MERGE]
PATCHES += MERGE_PATCHES

# After the drains: they anchor on the untouched fast-path condition these rewrite.
STALE_CLIENT_ARRAYS = [
    (
        'glDrawArrays: stale client arrays under an app program draw directly',
        'if(GLImmediate.totalEnabledClientAttributes==0&&mode<=6){GLctx.drawArrays(mode,first,count);return}',
        'if((GLImmediate.totalEnabledClientAttributes==0||(GL.currProgram&&GLImmediate.__fcStaleECA))&&mode<=6){GLctx.drawArrays(mode,first,count);return}',
    ),
    (
        'glDrawElements: stale client arrays under an app program draw directly',
        'if(GLImmediate.totalEnabledClientAttributes==0&&mode<=6&&GLctx.currentElementArrayBufferBinding){GLctx.drawElements(mode,count,type,indices);return}',
        'if((GLImmediate.totalEnabledClientAttributes==0||(GL.currProgram&&GLImmediate.__fcStaleECA))&&mode<=6&&GLctx.currentElementArrayBufferBinding){GLctx.drawElements(mode,count,type,indices);return}',
    ),
]
PATCHES += STALE_CLIENT_ARRAYS

# A DESTROYED CONTEXT MUST BE LET GO OF BY THE PAGE TOO.
#
# Qt destroys a 3D view's WebGL context when its document closes (measured 2026-09-11:
# one deleteContext per close), but the browser only reclaims a context once nothing
# references it, and the page's present pass keeps framebuffer/texture registries that
# hold the context object. Twenty open/close cycles left twenty live contexts; Chrome
# caps a page at 16 and evicts the oldest, which is the visible view. Tell the page, and
# forget this glue's own handles to the context's objects: Qt drops the context without
# deleting Coin's textures, framebuffers and programs, and a live WebGL object keeps its
# context alive; the immediate-mode renderer cache holds programs too, so it is rebuilt.
PATCHES += [
    (
        'deleteContext: tell the page which context is going away',
        'deleteContext:contextHandle=>{if(GL.currentContext===GL.contexts[contextHandle]){GL.currentContext=null}',
        'deleteContext:contextHandle=>{try{var __dc=GL.contexts[contextHandle],__g=__dc&&__dc.GLctx;if(__g){'
        'if(typeof window!=="undefined"&&window.__fcContextDeleted)window.__fcContextDeleted(__g);'
        'var __T=[GL.textures,GL.framebuffers,GL.renderbuffers,GL.buffers,GL.programs,GL.shaders];'
        'for(var __ti=0;__ti<__T.length;__ti++){var __t=__T[__ti];for(var __i=0;__i<__t.length;__i++){if(__t[__i]&&__t[__i].__fcGl===__g)__t[__i]=null}}'
        'if(typeof GLImmediate!=="undefined"&&GLImmediate.MapTreeLib){GLImmediate.rendererCache=GLImmediate.MapTreeLib.create();GLImmediate.currentRenderer=null;GLImmediate.lastRenderer=null;GLImmediate.fixedFunctionProgram=0}'
        '}}catch(e){}'
        'if(GL.currentContext===GL.contexts[contextHandle]){GL.currentContext=null}',
    ),
]


# ---- glDrawElements index type: a 32-bit-indexed mesh drew as half a mesh ------------
#
# emscripten's client-attribute glDrawElements path (GLImmediate.flush) ignores the
# `type` argument entirely: it scans and uploads client indices as Uint16 and always
# issues drawElements(..., UNSIGNED_SHORT, ...) -- also when the indices come from a
# bound ELEMENT_ARRAY_BUFFER. FreeCAD's mesh nodes draw with GL_UNSIGNED_INT
# (SoFCIndexedFaceSet.cpp MeshRenderer::renderGLArray under VBO, SoFCMeshObject.cpp
# renderFacesGLArray with client arrays). Each 32-bit index is then read as two 16-bit
# halves, [k, 0], and only the first half of the index data is consumed: a sphere
# rendered as a hemisphere, an STL as a burst of triangles fanning into vertex 0.
# Measured 2026-09-02 on dev: Mesh.createSphere(50, 200) with VBOs on renders as the
# lower half only; with ?vbo=0 (Coin's immediate path, which builds its own 16-bit
# indices) it is whole. VBOs on by default is what routed meshes here.
#
# Fix: remember the type at the glDrawElements entry, honour it in the three places
# flush() assumes 16 bits. The immediate-mode paths (glBegin/glEnd quads etc.) build
# their own Uint16 indices and pass numProvidedIndexes=0, so they keep UNSIGNED_SHORT.
INDEX_TYPE = [
    (
        # After the fast path's `return}` so the line-batching drain's marker
        # (`=>{GLImmediate.__mf();if(...`) stays intact.
        'glDrawElements records its index type',
        'GLctx.drawElements(mode,count,type,indices);return}GLImmediate.prepareClientAttributes(count,false);',
        'GLctx.drawElements(mode,count,type,indices);return}GLImmediate.__idxType=type;GLImmediate.prepareClientAttributes(count,false);',
    ),
    (
        'flush scans 32-bit client indices as 32-bit',
        'for(var i=0;i<numProvidedIndexes;i++){var currIndex=HEAPU16[ptr+i*2>>1];',
        'var __u32=GLImmediate.__idxType===5125;'
        'for(var i=0;i<numProvidedIndexes;i++){var currIndex=__u32?HEAPU32[ptr+i*4>>2]:HEAPU16[ptr+i*2>>1];',
    ),
    (
        # The anchor stops BEFORE the Uint16 heap expression (`.subarray` is not a bracket
        # access, so the mechanical growable derivation cannot reach it), and the 32-bit
        # branch views wasmMemory.buffer directly rather than naming a heap accessor: a
        # literal GROWABLE_HEAP_ in this table would flag the selftest corpus as growable
        # and break every classic anchor in it. The original Uint16 expression stays as
        # the else-branch, untouched.
        'flush uploads 32-bit client indices as 32-bit',
        'var indexBuffer=GL.getTempIndexBuffer(numProvidedIndexes<<1);'
        'GLctx.bindBuffer(GLctx.ELEMENT_ARRAY_BUFFER,indexBuffer);'
        'GLctx.bufferSubData(GLctx.ELEMENT_ARRAY_BUFFER,0,',
        'var __u32b=GLImmediate.__idxType===5125;'
        'var indexBuffer=GL.getTempIndexBuffer(numProvidedIndexes<<(__u32b?2:1));'
        'GLctx.bindBuffer(GLctx.ELEMENT_ARRAY_BUFFER,indexBuffer);'
        'GLctx.bufferSubData(GLctx.ELEMENT_ARRAY_BUFFER,0,'
        '__u32b?new Uint8Array(wasmMemory.buffer,ptr,numProvidedIndexes<<2):',
    ),
    (
        # Anchored on the polygon-mode patch's OUTPUT (numIndexes>0), which is also what
        # a released artifact contains.
        'flush draws with the recorded index type',
        'if(numIndexes>0){GLctx.drawElements(GLImmediate.mode,numIndexes,GLctx.UNSIGNED_SHORT,ptr)}'
        'else{GLctx.drawArrays(GLImmediate.mode,startIndex,numVertices)}',
        'if(numIndexes>0){GLctx.drawElements(GLImmediate.mode,numIndexes,'
        '(numProvidedIndexes&&GLImmediate.__idxType===5125)?GLctx.UNSIGNED_INT:GLctx.UNSIGNED_SHORT,ptr)}'
        'else{GLctx.drawArrays(GLImmediate.mode,startIndex,numVertices)}',
    ),
]
PATCHES += INDEX_TYPE

# ---- GL_COLOR_MATERIAL, for the VBO face path only ---------------------------------
#
# The emulation's vertex shader writes `v_color = a_color` and then, whenever lighting is
# on, THROWS IT AWAY:
#
#     v_color.xyz  = u_materialEmission.xyz;
#     v_color.xyz += u_lightModelAmbient.xyz * u_materialAmbient.xyz;
#     diffuse      = diffuseI * u_lightDiffuse0.xyz * u_materialDiffuse.xyz;
#
# There is no GL_COLOR_MATERIAL in it at all. Immediate mode survives that because Coin
# calls glColor3f per face and this table's 'glColor drives material colour' feeds it into
# materialDiffuse. SoBrepFaceSet's VBO path supplies colours as an interleaved ARRAY and
# never calls glColor, so every face shades with whatever material was last set -- measured
# as the whole assembly rendering SOLID BLACK with a correct silhouette under ?vbofaces=1.
#
# Applies wherever the COLOR client attribute is live, which is what real GL_COLOR_MATERIAL
# keys on. Begin/end draws enable it too and come out unchanged: 'glColor drives material
# colour' already keeps materialDiffuse equal to the glColor that a_color carries, so the
# uniform and the attribute hold the same value there.
PATCHES += [
    (
        'GL_COLOR_MATERIAL: shade a vertex-colour array by its own colour',
        'vsLightingPass+="  v_color.w = u_materialDiffuse.w;";'
        'vsLightingPass+="  v_color.xyz = u_materialEmission.xyz;";'
        'vsLightingPass+="  v_color.xyz += u_lightModelAmbient.xyz * u_materialAmbient.xyz;";',
        # COLOR is client attribute 2 (VERTEX:0, NORMAL:1, COLOR:2).
        # NOT gated on GLctx.currentArrayBufferBinding. With a VAO the buffer is recorded
        # per ATTRIBUTE and the global bind point is null by draw time, so that test never
        # fired for the very path it was written for: the faces kept shading from the
        # material uniform, which is how the model came out in FreeCAD's preselection
        # orange (255,90,0) while its buffers held the right colours all along.
        #
        # The client attribute alone is the correct condition, and it needs no extra cache
        # key: enabledAttributesKey already carries one bit per live attribute. Begin/end
        # draws enable COLOR too and are unaffected in result -- 'glColor drives material
        # colour' keeps materialDiffuse equal to the same glColor a_color carries.
        'var __fcCM=!!GLImmediate.enabledClientAttributes[2];'
        # DIFFUSE only, not AMBIENT_AND_DIFFUSE. Driving the ambient terms from a_color
        # as well double-counts the colour and CLIPS: the amber object came out
        # (255,90,0), its red channel saturated, against a declared (255,170,0) --
        # measured as cos 0.9692 to the declared hue where every other colour in the
        # frame sat at 1.0000. The ambient uniform is left alone.
        'var __fcD=__fcCM?"a_color":"u_materialDiffuse";'
        'vsLightingPass+="  v_color.w = "+__fcD+".w;";'
        'vsLightingPass+="  v_color.xyz = u_materialEmission.xyz;";'
        'vsLightingPass+="  v_color.xyz += u_lightModelAmbient.xyz * u_materialAmbient.xyz;";',
    ),
    (
        'GL_COLOR_MATERIAL: diffuse term',
        'vsLightingPass+="    vec3 diffuse = diffuseI * u_lightDiffuse"+lightId+".xyz * u_materialDiffuse.xyz;";',
        'vsLightingPass+="    vec3 diffuse = diffuseI * u_lightDiffuse"+lightId+".xyz * "+__fcD+".xyz;";',
    ),
]

# ---- per-vertex entry points: one heap-view check, no range-checked BigInt ---------------
#
# The immediate-mode paths (SoBrepFaceSet::renderShape for highlights, Coin's vertex cache
# renderImmediate, SoBrepEdgeSet) call glVertex3fv/glNormal3fv once per vertex. Profiled
# on a 4 s drag of EngineBlock (2026-09-11): growMemViews 10.7% and bigintToI53Checked
# 5.3% of the whole main thread, nearly all under these four functions -- the generated
# form checks the heap view THREE times per call and range-checks the pointer as a BigInt.
# One check, Number(), a local view: same reads, a third of the overhead.
PATCHES += [
    (
        'glVertex3fv: one heap-view check',
        '_emscripten_glVertex3fv(p){p=bigintToI53Checked(p);return _glVertex3f((growMemViews(),HEAPF32)[p/4],(growMemViews(),HEAPF32)[(p+4)/4],(growMemViews(),HEAPF32)[(p+8)/4])}',
        '_emscripten_glVertex3fv(p){growMemViews();var h=HEAPF32,i=Number(p)/4;return _glVertex3f(h[i],h[i+1],h[i+2])}',
    ),
    (
        'glNormal3fv: one heap-view check',
        '_emscripten_glNormal3fv(p){p=bigintToI53Checked(p);_glNormal3f((growMemViews(),HEAPF32)[p/4],(growMemViews(),HEAPF32)[(p+4)/4],(growMemViews(),HEAPF32)[(p+8)/4])}',
        '_emscripten_glNormal3fv(p){growMemViews();var h=HEAPF32,i=Number(p)/4;_glNormal3f(h[i],h[i+1],h[i+2])}',
    ),
    (
        'glColor3fv: one heap-view check',
        '_emscripten_glColor3fv(p){p=bigintToI53Checked(p);return _glColor3f((growMemViews(),HEAPF32)[p/4],(growMemViews(),HEAPF32)[(p+4)/4],(growMemViews(),HEAPF32)[(p+8)/4])}',
        '_emscripten_glColor3fv(p){growMemViews();var h=HEAPF32,i=Number(p)/4;return _glColor3f(h[i],h[i+1],h[i+2])}',
    ),
    (
        'glColor4fv: one heap-view check',
        '_emscripten_glColor4fv(p){p=bigintToI53Checked(p);return _glColor4f((growMemViews(),HEAPF32)[p/4],(growMemViews(),HEAPF32)[(p+4)/4],(growMemViews(),HEAPF32)[(p+8)/4],(growMemViews(),HEAPF32)[(p+12)/4])}',
        '_emscripten_glColor4fv(p){growMemViews();var h=HEAPF32,i=Number(p)/4;return _glColor4f(h[i],h[i+1],h[i+2],h[i+3])}',
    ),
]

# ---- GL_LIGHT_MODEL_TWO_SIDE ---------------------------------------------------------
#
# The emulation tracks GLEmulation.lightModelTwoSide (it is even in the renderer cache
# key) and then never reads it: the vertex shader lights every face with its own normal,
# so a face seen from behind comes out in ambient only -- dark. FreeCAD lights "Two side"
# by default, so on the desktop a back-facing face is as bright as a front-facing one.
#
# Measured 2026-09-11 on EngineBlock: the Draft BSpline/Circle faces lying ON the block's
# top (same 0.8 grey, same plane, normal pointing down) z-fight with the top face exactly
# as they do on the desktop, but here the loser is DARK, so the fight reads as a dark
# speckled top that swims with the camera. With both faces lit the same the fight is
# invisible, which is what the desktop shows.
#
# When two-sided lighting is on: light the vertex a second time with the flipped normal
# into a v_colorBack varying, and let the fragment shader pick by gl_FrontFacing. The
# vertex shader keeps computing into a local v_color so the passes above stay untouched.
PATCHES += [
    (
        'two-sided lighting: light the back face too',
        'vsLightingPass+="  v_color = clamp(v_color, 0.0, 1.0);"}',
        'vsLightingPass+="  v_color = clamp(v_color, 0.0, 1.0);";'
        'if(GLEmulation.lightModelTwoSide){__fcTS=true;vsLightingDefs+="varying vec4 v_colorBack;";'
        'vsLightingPass+=vsLightingPass.split("v_color").join("v_colorBack").split("ecNormal").join("ecNormalB")'
        '.replace("ecNormalB = normalize(","ecNormalB = -normalize(")}}',
    ),
    (
        'two-sided lighting: vertex shader writes v_colorF',
        '"varying vec4 v_color;",texUnitAttribList',
        # "v_color;" split so the original search text does not survive in the output
        '__fcTS?"varying vec4 v_colorF;":"varying vec4 "+"v_color;",texUnitAttribList',
    ),
    (
        'two-sided lighting: v_color is a local in the vertex shader',
        '"void main()","{","  vec4 ecPosition = u_modelView * a_position;"',
        '"void main()","{",__fcTS?"  vec4 v_color;":null,"  vec4 ecPosition = u_modelView * a_position;"',
    ),
    (
        'two-sided lighting: copy the front colour out',
        'vsLightingPass,"}",""]',
        'vsLightingPass,__fcTS?"  v_colorF = v_color;":null,"}",""]',
    ),
    (
        'two-sided lighting: fragment shader picks by gl_FrontFacing',
        '"varying vec4 v_color;",fogHeaderIfNeeded,fsClipPlaneDefs,fsAlphaTestDefs,"void main()","{",fsClipPlanePass,',
        '__fcTS?"varying vec4 v_colorF;varying vec4 v_colorBack;":"varying vec4 v_color;",fogHeaderIfNeeded,fsClipPlaneDefs,fsAlphaTestDefs,'
        '"void main()","{",__fcTS?"  vec4 v_color = gl_FrontFacing ? v_colorF : v_colorBack;":null,fsClipPlanePass,',
    ),
    # Nothing in this build ever turns the flag on: the wasm does not import glLightModeli
    # (Coin's SoGLLazyElement sends two-sided lighting through it), so the emulation's
    # default is what every lit draw gets -- the immediate-mode flush and the VBO face path
    # alike. FreeCAD's default Lighting is "Two side"; make that the default here too. A
    # glLightModelf(GL_LIGHT_MODEL_TWO_SIDE, 0) still switches it off if one ever arrives.
    (
        'two-sided lighting: on by default, as FreeCAD lights',
        'lightModelLocalViewer:false,lightModelTwoSide:false,',
        'lightModelLocalViewer:false,lightModelTwoSide:true,',
    ),
    (
        'two-sided lighting: __fcTS declared before the lighting pass',
        'var vsLightingDefs="";var vsLightingPass="";if(GLEmulation.lightingEnabled){',
        'var vsLightingDefs="";var vsLightingPass="";var __fcTS=false;if(GLEmulation.lightingEnabled){',
    ),
]


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
        a = emsdk6(t)
        n = text.count(a)
        if n:
            bad.append((a, 'Coin calls this; an abort here kills the whole program', n))
    n = text.count('HEAPU64)[(length+i*8)/8]') + text.count('HEAPU64[length+i*8>>3]')
    if n:
        bad.append(('glShaderSource length array read 64 bits at a time',
                    'Qt hands its shaders over in chunks with a GLint[] of lengths; read '
                    'this way they arrive truncated and the widget layer goes black as '
                    'soon as a 3D view exists', n))
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
        # SIX vertex writers, plus ONE in __mrgPrep.
        #
        # The line batcher expands a strip into pairs in place, which needs headroom
        # reserved exactly like a vertex writer does -- so it calls __grow() too, and
        # that is a legitimate seventh guard rather than a stray one. This invariant
        # failed the first link that ever contained it (34279403314): 'expected 6,
        # found 7', on a build whose patches had all applied correctly.
        n = text.count('GLImmediate.__grow()')
        if n != 7:
            bad.append(('growable immediate guards',
                        'expected 7 -- six vertex writers plus __mrgPrep -- found %d' % n,
                        n))
    if 'tempVertexBuffers1[idx]=[null]' not in text:
        bad.append(('oversize temp vertex buffer ring', 'absent -- an oversize batch dereferences undefined', 1))
    if text.count('__polyMode') < 2:
        bad.append(('polygon mode', 'absent -- Flat Lines overlays draw as solid black triangles', 1))
    # The index type must be recorded once and honoured at all three 16-bit assumptions;
    # a partial application draws 32-bit-indexed meshes as half a mesh with no error.
    n = text.count('GLImmediate.__idxType=type')
    if n != 1:
        bad.append(('glDrawElements index type recorded', 'expected exactly 1, found %d' % n, n))
    n = text.count('GLImmediate.__idxType===5125')
    if n != 3:
        bad.append(('glDrawElements index type honoured', 'expected 3 uses (scan, upload, draw), found %d' % n, n))
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

# Shift width -> the divisor wasm64 uses instead. Only these three occur in the GL glue.
_SHIFT_DIV = {'1': '2', '2': '4', '3': '8'}


def _relax_index(m):
    """Rewrite one escaped '>>N<closer>' into an alternation over every spelling.

    Deliberately anchored on the closer rather than relaxing every '>>N' in the body: an
    unanchored rule would also match genuine arithmetic and could move a patch onto the
    wrong site, which is far worse than not matching at all -- a miss fails the
    postcondition counts loudly, a mismatch does not.
    """
    n, closer = m.group(1), m.group(2)
    return '(?:>>>?%s(?:>>>0)?|/%s)%s' % (n, _SHIFT_DIV[n], closer)


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
    # A heap index has three spellings and the anchor must accept all of them.
    #
    #   plain wasm32      HEAPF32[(((param)+(12))>>2)]
    #   growable wasm32   the same, but >>2 may be >>>2>>>0 (unsigned-safe above 2 GB)
    #   wasm64            HEAPF32[(((param)+(12))/4)]
    #
    # The wasm64 form is a DIVISION, not a shift: a pointer is a BigInt there and BigInt
    # will not take >> with a Number operand, so emscripten divides instead. Measured on
    # emsdk 6.0.9 by linking the same fixed-function program with and without -m64
    # (.github/workflows/wasm64-probe.yml): >>1 becomes /2 and >>2 becomes /4, across
    # HEAPU16/HEAP32/HEAPU32/HEAPF32, with 92 shift-indexes becoming 0.
    #
    # Both closers matter. In the escaped pattern '>>2]' is '>>2\\]' and '>>2)' is
    # '>>2\\)'; the real glue uses the paren form inside the bracket, so relaxing only
    # ']' -- as this did -- would have matched nothing at wasm64.
    body = re.sub(r'>>(\d)(\\[\]\)])', _relax_index, body)
    # a converted function no longer needs its trailing semicolon
    body = body.replace(re.escape('};'), re.escape('}') + ';?')
    return re.compile(head + body), group


def _wasm64_regex(lit):
    """The same literal anchor, as a wasm64 build emits it.

    Only the heap INDEX moves. Everything else is byte-identical, which is why this is a
    relaxation of the literal rather than a second table: arithmetic such as
    GLImmediate.stride>>2 operates on a plain Number, not a pointer, and emscripten leaves
    it exactly as it was.
    """
    return re.compile(re.sub(r'>>(\d)(\\[\]\)])', _relax_index, re.escape(lit)))


def _to_wasm64(lit):
    """Rewrite a replacement's heap indexes into the divide form, so injected code reads
    in the same idiom as the glue around it."""
    return re.sub(r'>>(\d)([\]\)])',
                  lambda m: '/%s%s' % (_SHIFT_DIV[m.group(1)], m.group(2)), lit)



# ---- emsdk 6.0.9 ------------------------------------------------------------------------
#
# Measured on the first wasm64 FreeCAD.js this project ever linked (run 33961285555,
# emsdk 6.0.9, -m64 -pthread with ALLOW_MEMORY_GROWTH). Five things differ from the
# 3.1.70 glue the table was written against, and only the last needs hand-written text:
#
#   1. Every GL entry point is defined as _emscripten_glX and then aliased:
#          var _emscripten_glBegin=mode=>{...};var _glBegin=_emscripten_glBegin;
#      so an anchor on a definition head `var _glX=(...)=>{` must read `var _emscripten_glX=`.
#      The alias line is NOT a head (it is followed by an identifier), and is left alone.
#   2. With memory growth and pthreads the heap views are re-fetched at every access:
#          HEAPF32[param+12>>2]   ->   (growMemViews(),HEAPF32)[(param+12)/4]
#      -- the growable accessor of old is gone, the index is a division (wasm64), and an
#      index EXPRESSION is parenthesised. No HEAPU64[ appears in this glue at all (the views
#      come through growMemViews), which is why growMemViews() is the detection tell.
#   3. Unimplemented fixed-function corners abort instead of throwing:
#          throw"glTexGeni: TODO"   ->   abort("glTexGeni: TODO")
#      Same consequence for Coin -- worse, in fact: abort() takes the whole program, not
#      just the viewport -- so those nine sites still become no-ops and the postconditions
#      count the abort form too.
#   4. A pointer parameter turns the arrow into a function with a coercion prologue:
#          function _emscripten_glDrawElements(mode,count,type,indices,start,end){
#              indices=bigintToI53Checked(indices);...
#      (the same shape the growable form had, with a different coercion).
#   5. Five sites moved around the anchor: glMaterialfv is now followed by glMatrixMode
#      rather than by its own alias, glColor3f is defined after the glColor4f alias, the
#      GLImmediate.init() callback is followed by hoisted declarations, the index upload
#      goes through webglBufferSubData(byteSize,ptr), and numIndexes is tested for truth.
#
# 1-4 are one mechanical derivation, checked by the selftest against strings copied from
# that glue. 5 is a table of fixups by patch name, and one full override.
_EMSDK6_HEAP_IDX = re.compile(r'HEAP(F32|F64|U8|U16|U32|U64|8|16|32)\[([^\[\]]*?)(?:>>([123]))?\]')


def _emsdk6_heap(m):
    heap, expr, shift = m.group(1), m.group(2), m.group(3)
    if shift:
        if re.search(r'[+\-*]', expr):
            expr = '(%s)' % expr
        expr = expr + '/' + _SHIFT_DIV[shift]
    return '(growMemViews(),HEAP%s)[%s]' % (heap, expr)


def emsdk6(s):
    """The same literal, as the emsdk 6.0.9 glue writes it (rules 1-4 above)."""
    s = re.sub(r'var (_gl\w+)=(?=\(|[A-Za-z_$][\w$]*=>)', r'var _emscripten\1=', s)
    s = _EMSDK6_HEAP_IDX.sub(_emsdk6_heap, s)
    s = s.replace('HEAPF32.subarray(', '(growMemViews(),HEAPF32).subarray(')
    s = re.sub(r'throw"(gl[^"]*)"(\+\w+)?',
               lambda m: 'abort("%s"%s)' % (m.group(1), m.group(2) or ''), s)
    return s


# Rule 5: applied to the derived old/new/marker of the named patch, in order.
_EMSDK6_FIXUPS = {
    'getWasmTableEntry null-function guard': [
        ('wasmTable.get(funcPtr)', 'wasmTable.get(BigInt(funcPtr))')],
    'glColor drives material colour': [
        (';var _glColor3f=', ';var _glColor4f=_emscripten_glColor4f;var _emscripten_glColor3f=')],
    'glMaterialfv: EMISSION and AMBIENT_AND_DIFFUSE': [
        ('}};var _emscripten_glMaterialfv=', '}}var _emscripten_glMatrixMode=')],
    'init immediate mode on context switch (FCWEBMCC)': [
        ('GLEmulation.init();for(var i=0;i<32;++i)', 'var _emscripten_glDrawArrays;')],
    'line batching drain: glDrawElements': [
        ('var _emscripten_glDrawElements=(mode,count,type,indices,start,end)=>{',
         'function _emscripten_glDrawElements(mode,count,type,indices,start,end){'
         'indices=bigintToI53Checked(indices);')],
    'flush draws with the recorded index type': [
        ('if(numIndexes>0){', 'if(numIndexes){')],
}
# The upload site changed shape entirely: the byte count is a variable and the copy goes
# through webglBufferSubData(target,offset,byteSize,ptr), which copies raw heap bytes --
# so a 32-bit index buffer needs only the doubled byte count, no second typed view.
_EMSDK6_OVERRIDES = {
    'flush uploads 32-bit client indices as 32-bit': (
        'var byteSize=numProvidedIndexes<<1;var indexBuffer=GL.getTempIndexBuffer(byteSize);'
        'GLctx.bindBuffer(GLctx.ELEMENT_ARRAY_BUFFER,indexBuffer);'
        'webglBufferSubData(GLctx.ELEMENT_ARRAY_BUFFER,0,byteSize,ptr);',
        'var __u32b=GLImmediate.__idxType===5125;'
        'var byteSize=numProvidedIndexes<<(__u32b?2:1);var indexBuffer=GL.getTempIndexBuffer(byteSize);'
        'GLctx.bindBuffer(GLctx.ELEMENT_ARRAY_BUFFER,indexBuffer);'
        'webglBufferSubData(GLctx.ELEMENT_ARRAY_BUFFER,0,byteSize,ptr);'),
}
# The lenient counters, at the two sites whose 6.0.9 shape the derivation cannot reach
# (a function with a coercion prologue; an arrow whose whole body is the call).
_EMSDK6_COUNT_OVERRIDES = {
    'count glTexGenfv': (
        'function _emscripten_glTexGenfv(coord,pname,param){param=bigintToI53Checked(param);return 0}',
        'function _emscripten_glTexGenfv(coord,pname,param){param=bigintToI53Checked(param);return %s}' % _count('glTexGenfv')),
    'count glTexGeni': (
        'var _emscripten_glTexGeni=(coord,pname,param)=>0;',
        'var _emscripten_glTexGeni=(coord,pname,param)=>%s;' % _count('glTexGeni')),
}


def emsdk6_entry(entry):
    """(old, new, marker) for one table entry, as the 6.0.9 glue has them."""
    name = entry[0]
    if name in _EMSDK6_OVERRIDES:
        o = _EMSDK6_OVERRIDES[name]
        return o[0], o[1], (o[2] if len(o) > 2 else o[1])
    old, new = emsdk6(entry[1]), emsdk6(entry[2])
    marker = emsdk6(entry[3]) if len(entry) > 3 else new
    for a, b in _EMSDK6_FIXUPS.get(name, ()):
        old, new, marker = old.replace(a, b), new.replace(a, b), marker.replace(a, b)
    return old, new, marker


def emsdk6_count(name, old, new):
    if name in _EMSDK6_COUNT_OVERRIDES:
        return _EMSDK6_COUNT_OVERRIDES[name]
    return emsdk6(old), emsdk6(new)


def _selftest_emsdk6():
    # Derivations pinned to strings copied from the first wasm64 FreeCAD.js.
    assert emsdk6('GLEmulation.materialShininess[0]=HEAPF32[param>>2]}else{throw"glMaterialfv: TODO: "+pname}') == \
        'GLEmulation.materialShininess[0]=(growMemViews(),HEAPF32)[param/4]}else{abort("glMaterialfv: TODO: "+pname)}'
    assert emsdk6('var currIndex=HEAPU16[ptr+i*2>>1];') == 'var currIndex=(growMemViews(),HEAPU16)[(ptr+i*2)/2];'
    assert emsdk6('odelAmbient[3]=HEAPF32[param+12>>2]}') == 'odelAmbient[3]=(growMemViews(),HEAPF32)[(param+12)/4]}'
    assert emsdk6('var _glEnd=()=>{GLImmediate.') == 'var _emscripten_glEnd=()=>{GLImmediate.'
    assert emsdk6('var _glEnableClientState=cap=>{') == 'var _emscripten_glEnableClientState=cap=>{'
    assert emsdk6('var _glColor4f=_emscripten_glColor4f;') == 'var _glColor4f=_emscripten_glColor4f;'
    assert emsdk6('throw"glTexCoord3f: TODO"') == 'abort("glTexCoord3f: TODO")'
    assert emsdk6('GLImmediate.vertexCounter/(GLImmediate.stride>>2)') == 'GLImmediate.vertexCounter/(GLImmediate.stride>>2)'
    assert emsdk6_entry([e for e in PATCHES if e[0] == 'init immediate mode on context switch (FCWEBMCC)'][0])[0] == \
        'GLImmediate.init());var _emscripten_glDrawArrays;'
    # Every entry, in its 6.0.9 form, applies and is idempotent -- the same fixture the
    # legacy form gets, built from the table itself.
    src6 = 'growMemViews()' + ''.join(emsdk6_entry(e)[0] for e in PATCHES)
    out6, st6 = apply(src6, counting=False)
    bad6 = [(n, s) for n, s in st6 if s == 'NOT FOUND']
    assert not bad6, ('emsdk6 form not matched: %r' % bad6)
    assert all('emsdk6 form' in s or s == 'already applied' for _, s in st6), st6
    assert apply(out6, counting=False)[0] == out6, 'emsdk6 form not idempotent'
    # No postcondition count on this fixture: concatenating every anchor makes one vertex
    # writer appear twice, exactly as the legacy fixture does. The real artifact is checked
    # by --check in link-freecad.yml, and did pass: 1/6/1/3 on run 33961285555's glue.


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
    #
    # is_growable is False on any CURRENT link. emsdk 6.0.9 no longer emits the
    # GROWABLE_HEAP_*() accessor form at all -- measured by linking the same program with
    # ALLOW_MEMORY_GROWTH=1 on both targets, which produced the growth machinery and zero
    # accessors (.github/workflows/wasm64-probe.yml). The branch stays for the shipped
    # 3.1.70-era asset, which still carries them.
    is_growable = 'GROWABLE_HEAP_' in text
    # A wasm64 glue indexes the heap by division rather than by shift, because a pointer is
    # a BigInt and BigInt will not take >> with a Number operand. HEAPU64 is the cleanest
    # tell: 5 occurrences at wasm64, 0 at wasm32, growable or not.
    is_wasm64 = 'HEAPU64[' in text
    # emsdk 6.0.9 re-fetches the heap views through growMemViews(); see emsdk6().
    is_emsdk6 = 'growMemViews()' in text
    for entry in PATCHES:
        name, old, new = entry[0], entry[1], entry[2]
        # a 4th field is the text that proves the fix is in effect, for when a
        # LATER patch rewrites the surroundings so `new` no longer appears whole
        marker = entry[3] if len(entry) > 3 else new
        if is_growable and old not in text:
            old, new, marker = growable(old), growable(new), growable(marker)
        if is_emsdk6:
            o6, n6, m6 = emsdk6_entry(entry)
            if o6 in text:
                text = text.replace(o6, n6, 1)
                status.append((name, 'applied (emsdk6 form)'))
                continue
            # A one-character marker (the no-op `0`) proves nothing; leave those to the
            # legacy arm below and to the postconditions, which count the abort forms.
            if o6 != old and len(m6) > 1 and m6 in text:
                status.append((name, 'already applied (emsdk6 form)'))
                continue
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
        # Same idea for a wasm64 glue: the anchor is the literal with its heap indexes
        # relaxed to accept either spelling, and the replacement is written in the divide
        # idiom so the injected code matches the code around it.
        if is_wasm64:
            m = _wasm64_regex(entry[1]).search(text)
            if m:
                text = text[:m.start()] + _to_wasm64(entry[2]) + text[m.end():]
                status.append((name, 'applied (wasm64 form)'))
                continue
            if _wasm64_regex(marker if len(entry) > 3 else entry[2]).search(text):
                status.append((name, 'already applied (wasm64 form)'))
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
    _selftest_emsdk6()
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
        # An entry whose output a LATER patch rewrites carries a 4th field naming the
        # text that proves it is in effect; `new` itself is then legitimately absent
        # (glNormal3f outside begin/end -> growable glNormal3f; polygon-mode draw tail
        # -> index-type draw). Assert on what apply() itself detects on.
        name, marker = e[0], (e[3] if len(e) > 3 else e[2])
        assert marker in out, name

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

    # ---- wasm64 -------------------------------------------------------------------
    # A wasm64 glue indexes the heap by division, not by shift: a pointer is a BigInt
    # there and BigInt will not take >> with a Number operand. Measured on emsdk 6.0.9
    # by linking the same fixed-function program with and without -m64
    # (.github/workflows/wasm64-probe.yml): >>1 -> /2 and >>2 -> /4, 92 shift-indexes
    # became 0, and the .wasm grew 12.7 percent.
    #
    # Built the same way as the fixture above, from the table itself, so it cannot go
    # stale. The HEAPU64 prefix is what apply() detects the target on.
    #
    # This is the check that would have caught the old behaviour: before the divide
    # relaxation, _growable_regex only ever relaxed '>>N]', while the real glue closes
    # with '>>N)' inside the bracket -- so at wasm64 every one of these anchors would
    # have missed, and the tool would have refused the link rather than silently
    # mispatching it. Loud, but a day late.
    # HEAPU64[i], not HEAPU64[0]: several throw-removal patches use "0" as their marker,
    # so a literal zero in the preamble makes them report "already applied" and could mask
    # a genuine miss. The detector only needs the view name.
    w64_src = 'var _probe=HEAPU64[i];' + ''.join(_to_wasm64(e[1]) for e in PATCHES)
    _w64_out, w64_status = apply(w64_src, counting=False)
    w64_bad = [(n, st) for n, st in w64_status if st == 'NOT FOUND']
    assert not w64_bad, ('wasm64 form not matched: %r' % w64_bad)
    # Only the anchors that actually carry a heap index should need the new mode; if this
    # number climbs, the relaxation has grown teeth it was not meant to have.
    via64 = [n for n, st in w64_status if 'wasm64 form' in st]
    assert 0 < len(via64) <= 8, ('unexpected wasm64-form count: %d %r' % (len(via64), via64))

    # And the relaxation must not have bought matches with looseness: on a wasm64 file that
    # genuinely lacks every site, every patch must still report NOT FOUND, exactly as it
    # does at wasm32. A mode that matches something here would be free to land a patch on
    # the wrong site, which the postcondition counts cannot catch.
    _, s5 = apply('var _p=HEAPU64[i];function unrelated(){}', counting=False)
    assert all(st == 'NOT FOUND' for _, st in s5), s5

    print('patch-freecad-js selftest OK (%d patches + %d counters, %d via wasm64 form)'
          % (len(PATCHES), len(COUNTING_PATCHES), len(via64)))


if __name__ == '__main__':
    if len(sys.argv) == 2 and sys.argv[1] == '--selftest':
        selftest()
    else:
        sys.exit(main())
