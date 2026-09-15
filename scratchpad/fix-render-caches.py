"""Make the two render-cache kill switches in patches/freecad.patch conditional on
FCWEB_NO_DLISTS (set by pre-gui.js for ?dlists=0). Byte-level edit, hunks recounted,
sections dry-run at -F0. Both sections are LF.

    python scratchpad/fix-render-caches.py
"""
import io
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
P = os.path.join(ROOT, 'patches', 'freecad.patch')
LF = b'\n'
HDR = re.compile(rb'^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(.*)$')


def recount(raw):
    lines = raw.split(LF)
    out, i = [], 0
    while i < len(lines):
        l = lines[i]
        m = HDR.match(l.rstrip(b'\r'))
        if not m:
            out.append(l); i += 1; continue
        cr = b'\r' if l.endswith(b'\r') else b''
        body, j = [], i + 1
        while j < len(lines):
            t = lines[j]
            if HDR.match(t.rstrip(b'\r')) or t.startswith((b'--- ', b'diff ')):
                break
            if t.startswith((b' ', b'+', b'-', b'\\')) or t == b'':
                body.append(t); j += 1; continue
            break
        while body and body[-1] == b'':
            body.pop(); j -= 1
        oc = sum(1 for t in body if t.startswith((b' ', b'-')))
        nc = sum(1 for t in body if t.startswith((b' ', b'+')))
        out.append(b'@@ -%s,%d +%s,%d @@%s%s' % (m.group(1), oc, m.group(3), nc, m.group(5), cr))
        out.extend(body); i = j
    return LF.join(out)


def section(raw, path):
    i = raw.find(b'diff -ruNp a/' + path.encode())
    j = raw.find(b'\ndiff -ruNp ', i + 1)
    return i, (len(raw) if j < 0 else j + 1)


OLD1 = (b'+#if defined(__EMSCRIPTEN__)\n'
        b'+    // wasm: GL display lists are stubbed, so Coin separator render caches replay\n'
        b'+    // NOTHING on 2nd+ frames (first render direct = geometry visible, every\n'
        b'+    // redraw after = blank). Disable render caching engine-wide.\n'
        b'+    SoSeparator::setNumRenderCaches(0);\n'
        b'+#endif\n')
NEW1 = (b'+#if defined(__EMSCRIPTEN__)\n'
        b'+    // wasm: GL display lists are recorded and replayed by the glue since 2026-09-14\n'
        b'+    // (gl_legacy_stubs.c -> __fcDL), so Coin\'s separator render caches work as on the\n'
        b'+    // desktop. ?dlists=0 sets FCWEB_NO_DLISTS: lists answer 0 again and caching must\n'
        b'+    // then be off engine-wide, or every redraw after the first draws nothing.\n'
        b'+    if (std::getenv("FCWEB_NO_DLISTS")) {\n'
        b'+        SoSeparator::setNumRenderCaches(0);\n'
        b'+    }\n'
        b'+#endif\n')
OLD2 = (b'+#if defined(__EMSCRIPTEN__)\n'
        b'+    // wasm: display lists are stubbed (glGenLists returns 0), so ON/AUTO render\n'
        b'+    // caching produces permanently-empty caches \xe2\x80\x94 children are never traversed\n'
        b'+    // after the first frame and nothing draws. Force caching OFF.\n'
        b'+    caching = SoSeparator::OFF;\n'
        b'+    if (pcViewProviderRoot) {\n'
        b'+        pcViewProviderRoot->renderCaching = SoSeparator::OFF;\n'
        b'+    }\n'
        b'+#endif\n')
NEW2 = (b'+#if defined(__EMSCRIPTEN__)\n'
        b'+    // wasm: display lists are real since 2026-09-14 (recorded and replayed by the\n'
        b'+    // glue), so render caching behaves as on the desktop. With ?dlists=0 they answer 0\n'
        b'+    // again and caching must be OFF, or nothing draws after the first frame.\n'
        b'+    if (std::getenv("FCWEB_NO_DLISTS")) {\n'
        b'+        caching = SoSeparator::OFF;\n'
        b'+        if (pcViewProviderRoot) {\n'
        b'+            pcViewProviderRoot->renderCaching = SoSeparator::OFF;\n'
        b'+        }\n'
        b'+    }\n'
        b'+#endif\n')


def main():
    raw = io.open(P, 'rb').read()
    for path, old, new in (('src/Gui/StartupProcess.cpp', OLD1, NEW1),
                           ('src/Gui/View3DInventorViewer.cpp', OLD2, NEW2)):
        i, j = section(raw, path)
        sec = raw[i:j]
        assert sec.count(old) == 1, (path, sec.count(old))
        sec = recount(sec.replace(old, new))
        assert b'\r\n' not in sec
        raw = raw[:i] + sec + raw[j:]
    # <cstdlib> for std::getenv: View3DInventorViewer.cpp includes plenty already; StartupProcess
    # has <cstdio> from our own hunk -- add <cstdlib> beside it.
    i, j = section(raw, 'src/Gui/StartupProcess.cpp')
    sec = raw[i:j]
    a = b'+#include <cstdio>\n'
    assert sec.count(a) == 1
    sec = recount(sec.replace(a, a + b'+#include <cstdlib>\n'))
    raw = raw[:i] + sec + raw[j:]
    io.open(P, 'wb').write(raw)
    print('patched')
    # dry-run both sections against pristine files
    work = os.path.join(ROOT, 'scratchpad', 'rc-work')
    for path in ('src/Gui/StartupProcess.cpp', 'src/Gui/View3DInventorViewer.cpp'):
        pristine = os.path.join(ROOT, 'scratchpad', 'tree113', path)
        if not os.path.exists(pristine):
            import urllib.request
            os.makedirs(os.path.dirname(pristine), exist_ok=True)
            urllib.request.urlretrieve('https://raw.githubusercontent.com/FreeCAD/FreeCAD/1.1.3/' + path, pristine)
        os.makedirs(os.path.join(work, os.path.dirname(path)), exist_ok=True)
        io.open(os.path.join(work, path), 'wb').write(io.open(pristine, 'rb').read())
        i, j = section(raw, path)
        io.open(os.path.join(work, 'sec.diff'), 'wb').write(raw[i:j])
        r = subprocess.run(['patch', '-p1', '-F0', '--dry-run', '-i', 'sec.diff'], cwd=work, capture_output=True, text=True)
        print('%s dry-run rc=%d %s%s' % (path, r.returncode, r.stdout.strip()[-200:], r.stderr.strip()[-200:]))
        if r.returncode:
            sys.exit(r.returncode)


if __name__ == '__main__':
    main()
