#!/usr/bin/env python3
"""PROTOTYPE, NOT SHIPPED -- merge immediate-mode line blocks in emscripten's GLImmediate.

Applies to a linked play-gui/FreeCAD.js. Measured on BIMExample:

    draws/frame  4101 -> 465        fps  ~10 -> 23-27

...and it is WRONG: the dimension/annotation text loses ~325 pixels (Coin's glyph path).
Do not ship until that is pixel-identical (scratchpad/imgdiff.py, viewport region only --
the document tab bar legitimately differs between runs).

WHY IT IS WORTH FINISHING: 93% of a BIM scene's draw calls are two-vertex LINE_STRIPs,
one per edge, and each carries a full bufferSubData + vertexAttribPointer + enable +
draw + disable. Batching them at the WebGL wrapper level does NOT work (tried: 3x
slower) because the per-segment setup is emitted regardless. It has to happen here,
where glBegin/glEnd decide when to flush.

THE IDEA: a two-vertex LINE_STRIP block does not flush; the next identical block appends
to the same vertex accumulator, and one flush covers them all as GL_LINES (N two-vertex
strips == N segments). Each deferred block still tears down exactly as an undeferred one
does, and everything flush() needs is snapshotted and restored at flush time -- leaving
the emulation half-torn-down was what broke Coin's client-array text path.

BUGS ALREADY FIXED HERE (each cost a measurement round):
  - the modelview/projection matrix is uploaded at FLUSH time and glTranslate never
    touches the GL context, so a batch may only span blocks with the same
    matrixVersion -- without that check every text glyph drew at one position
  - _glEnableClientState / _glDisableClientState / _glDrawArrays / _glDrawElements read
    the immediate-mode client-attribute state and never touch the GL context either, so
    they need an explicit drain
  - do NOT drain inside setClientAttribute: prepareClientAttributes calls it during
    glEnd, so it re-enters and corrupts the batch (that made things worse, 6171 px)

STILL OPEN: ~325 pixels in the annotation text. Next thing to check is whether the glyph
path depends on any other state that flush() applies late -- lighting/material uniforms
are applied by renderer.prepare() the same way the matrix is, and are not in the key.

The page side also needs a drain hook: while a batch accumulates NO GL call happens, so
the next real context call must drain it (see the reverted block in freecad-gui.html
history, commit message of the redundant-state-elimination change).
"""
import sys

TAIL = ('GLImmediate.disableBeginEndClientAttributes();GLImmediate.mode=-1;'
        'GLImmediate.enabledClientAttributes=GLImmediate.enabledClientAttributes_preBegin;'
        'GLImmediate.clientAttributes=GLImmediate.clientAttributes_preBegin;'
        'GLImmediate.currentRenderer=null;GLImmediate.modifiedClientAttributes=true')

OLD_END = ('var _glEnd=()=>{GLImmediate.prepareClientAttributes(GLImmediate.rendererComponents[GLImmediate.VERTEX],true);'
           'GLImmediate.firstVertex=0;GLImmediate.lastVertex=GLImmediate.vertexCounter/(GLImmediate.stride>>2);'
           'if(GLctx.currentArrayBufferBinding){GLctx.bindBuffer(GLctx.ARRAY_BUFFER,null);GLctx.currentArrayBufferBinding=null;}'
           'GLImmediate.flush();' + TAIL + '}')

HELPERS = (
 'GLImmediate.__mrgN=0;GLImmediate.__mrgPend=false;GLImmediate.__mrgPrevVC=0;GLImmediate.__mrgSnap=null;'
 'GLImmediate.__mrgOn=!/[?&]nomerge=1/.test(location.search);globalThis.__GLI=GLImmediate;'
 'GLImmediate.__mf=()=>{if(GLImmediate.__mrgPend)GLImmediate.__flushMerged()};'
 'GLImmediate.__flushMerged=()=>{'
 'if(!GLImmediate.__mrgPend)return;var S=GLImmediate.__mrgSnap;'
 'GLImmediate.__mrgPend=false;GLImmediate.__mrgN=0;GLImmediate.__mrgSnap=null;'
 'var kCA=GLImmediate.clientAttributes,kECA=GLImmediate.enabledClientAttributes,'
 'kRC=GLImmediate.rendererComponents,kMode=GLImmediate.mode,kStride=GLImmediate.stride;'
 'GLImmediate.clientAttributes=S.ca;GLImmediate.enabledClientAttributes=S.eca;'
 'GLImmediate.rendererComponents=S.rc;GLImmediate.stride=S.stride;'
 'GLImmediate.currentRenderer=null;GLImmediate.modifiedClientAttributes=true;'
 'GLImmediate.firstVertex=0;GLImmediate.lastVertex=GLImmediate.vertexCounter/(GLImmediate.stride>>2);'
 'GLImmediate.mode=1;GLImmediate.flush();'
 'GLImmediate.disableBeginEndClientAttributes();'
 'GLImmediate.clientAttributes=kCA;GLImmediate.enabledClientAttributes=kECA;'
 'GLImmediate.rendererComponents=kRC;GLImmediate.stride=kStride;GLImmediate.mode=kMode;'
 'GLImmediate.currentRenderer=null;GLImmediate.modifiedClientAttributes=true;'
 'GLImmediate.vertexCounter=0;GLImmediate.__mrgPrevVC=0};')

NEW_END = ('var _glEnd=()=>{GLImmediate.prepareClientAttributes(GLImmediate.rendererComponents[GLImmediate.VERTEX],true);'
           'GLImmediate.firstVertex=0;GLImmediate.lastVertex=GLImmediate.vertexCounter/(GLImmediate.stride>>2);'
           'if(GLctx.currentArrayBufferBinding){GLctx.bindBuffer(GLctx.ARRAY_BUFFER,null);GLctx.currentArrayBufferBinding=null;}'
           'if(GLImmediate.__mrgOn&&GLImmediate.mode===3&&GLImmediate.stride&&'
           '(GLImmediate.vertexCounter-GLImmediate.__mrgPrevVC)/(GLImmediate.stride>>2)===2){'
           'GLImmediate.__mrgPend=true;GLImmediate.__mrgN++;'
           'GLImmediate.__mrgSnap={ca:GLImmediate.clientAttributes,eca:GLImmediate.enabledClientAttributes,'
           'rc:GLImmediate.rendererComponents,stride:GLImmediate.stride,'
           'mv0:GLImmediate.matrixVersion[0],mv1:GLImmediate.matrixVersion[1]};'
           + TAIL + ';return;}'
           'if(GLImmediate.__mrgPend){var __m=GLImmediate.mode;GLImmediate.__flushMerged();GLImmediate.mode=__m;}'
           'GLImmediate.flush();' + TAIL + '}')

OLD_VC = 'GLImmediate.mode=mode;GLImmediate.vertexCounter=0;'
NEW_VC = ('GLImmediate.mode=mode;'
          'if(GLImmediate.__mrgPend&&mode===3&&GLImmediate.__mrgSnap&&'
          'GLImmediate.matrixVersion[0]===GLImmediate.__mrgSnap.mv0&&'
          'GLImmediate.matrixVersion[1]===GLImmediate.__mrgSnap.mv1){'
          'GLImmediate.__mrgPrevVC=GLImmediate.vertexCounter;}'
          'else{GLImmediate.__mf();GLImmediate.vertexCounter=0;GLImmediate.__mrgPrevVC=0;}')

DRAINS = ['var _glDrawArrays=(mode,first,count)=>{',
          'var _glDrawElements=(mode,count,type,indices,start,end)=>{',
          'var _glEnableClientState=cap=>{', 'var _glDisableClientState=cap=>{']


def main():
    path = sys.argv[1]
    s = open(path, errors='replace').read()
    for needle in [OLD_END, OLD_VC] + DRAINS:
        if s.count(needle) != 1:
            print('site not found exactly once: %r' % needle[:60])
            return 1
    s = s.replace(OLD_END, HELPERS + NEW_END).replace(OLD_VC, NEW_VC)
    for d in DRAINS:
        s = s.replace(d, d + 'GLImmediate.__mf();')
    open(path, 'w').write(s)
    print('applied (PROTOTYPE -- verify with scratchpad/imgdiff.py before trusting)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
