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

Two fixes:

  getCurTexUnit    Returns a neutral texture unit when s_texUnits has not been set up
                   yet. Without it, texture-env hooks dereference undefined during the
                   first frames and the 3D view never comes up.

  GLImmediate      Caches the result of GLctx.isProgram() per renderer, and drops a
  renderer reuse   cached renderer whose program or GL context is no longer valid.
                   The isProgram() call is a GPU round-trip on every flush -- this is
                   the "interaction 1 -> 38 fps" fix -- and the validity check is what
                   stops a renderer from a dead context being reused.

Usage: patch-freecad-js.py <FreeCAD.js> [--check]
"""
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
]


def apply(text):
    """Return (patched_text, [status per patch]). Idempotent."""
    status = []
    for name, old, new in PATCHES:
        if new in text:
            status.append((name, 'already applied'))
        elif old in text:
            text = text.replace(old, new, 1)
            status.append((name, 'applied'))
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
    if not check and out != src:
        p.write_text(out)
        print('patched %s' % p)
    return 0


def selftest():
    src = ('function getCurTexUnit(){return s_texUnits[s_activeTexture]}'
           'getRenderer(){if(GLImmediate.currentRenderer){return GLImmediate.currentRenderer}'
           'var renderer=keyView.get();if(!renderer){x()}')
    out, status = apply(src)
    assert all(s == 'applied' for _, s in status), status
    assert 'if(!s_texUnits)' in out
    assert '_fcProgOK' in out and out.count('_fcProgOK') >= 4
    # idempotent: a second pass must change nothing
    out2, status2 = apply(out)
    assert out2 == out, 'not idempotent'
    assert all(s == 'already applied' for _, s in status2), status2
    # a file missing the sites must be reported, not silently "fixed"
    _, s3 = apply('function unrelated(){}')
    assert all(s == 'NOT FOUND' for _, s in s3), s3
    print('patch-freecad-js selftest OK')


if __name__ == '__main__':
    if len(sys.argv) == 2 and sys.argv[1] == '--selftest':
        selftest()
    else:
        sys.exit(main())
