# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) Virtastic
"""Does the 3D viewport draw anything, and can a headless run tell?

    python tools/pixel-probe.py <serve-dir> <port> [--gl swiftshader|angle|egl]

RELEASE-PLAN 2.9 (rendering correctness) was blocked on the belief that a headless run
cannot judge rendering because requestAnimationFrame does not fire. That is not true, and
this probe is the measurement:

  * Chromium headless with --use-gl=angle --use-angle=swiftshader gives a real WebGL2
    context: "ANGLE (Google, Vulkan 1.3.0 (SwiftShader Device (Subzero)), SwiftShader
    driver)".
  * rAF ticks at ~60 Hz: 179 callbacks in 3 seconds, measured.
  * Qt's canvas is 1280x720 and lives inside a SHADOW root (div#qt-shadow-container), so
    document.querySelectorAll("canvas") does not find it. Walk shadowRoot.
  * A page screenshot taken before the loading overlay hides is almost pure black -- the
    overlay is #0a0a09 -- and looks exactly like a viewport that rendered nothing. Wait
    for display:none, or force it.
  * A WebGL canvas without preserveDrawingBuffer is cleared once the frame composites, so
    a grab between frames is black however much was drawn. Copy it inside a rAF callback.

With all four of those handled, the canvas is STILL entirely one colour (0, 0, 0) while
Coin reports traversing the scene (FCWEB-USEL GLRenderBelowPath children=8). So the open
question is no longer "can headless render" -- it is "why does the legacy GL emulation path
draw nothing under SwiftShader", which is answerable. Start here rather than from scratch.
"""
import argparse
import os
import subprocess
import sys
import tempfile
import time

CAPTURE = """
(() => {
  window.__GATE = [];
  let real = null;
  Object.defineProperty(window, 'fcwebLogRing', {
    configurable: true,
    get() { return (line) => { try { window.__GATE.push(String(line)); } catch (e) {}
                               try { if (real) real(line); } catch (e) {} }; },
    set(fn) { real = fn; },
  });
  window.__RAF = 0;
  const tick = () => { window.__RAF++; requestAnimationFrame(tick); };
  requestAnimationFrame(tick);
})();
"""

GL_INFO = """(() => {
  const c = document.createElement('canvas');
  const gl = c.getContext('webgl2') || c.getContext('webgl');
  if (!gl) return {webgl: false};
  const dbg = gl.getExtension('WEBGL_debug_renderer_info');
  return {
    webgl: true,
    version: gl.getParameter(gl.VERSION),
    vendor: dbg ? gl.getParameter(dbg.UNMASKED_VENDOR_WEBGL) : gl.getParameter(gl.VENDOR),
    renderer: dbg ? gl.getParameter(dbg.UNMASKED_RENDERER_WEBGL) : gl.getParameter(gl.RENDERER),
    raf: window.__RAF,
  };
})()"""

BOX_PY = """
import FreeCAD as App
import FreeCADGui as Gui
import sys as _s

doc = App.newDocument("Pixels")
b = doc.addObject("Part::Box", "Box")
b.Length, b.Width, b.Height = 40.0, 25.0, 15.0
doc.recompute()
try:
    Gui.activeDocument().activeView().viewAxonometric()
    Gui.SendMsgToActiveView("ViewFit")
except Exception as e:
    _s.__stderr__.write("PIXELS view error " + repr(e) + chr(10))
_s.__stderr__.write("PIXELS {'built': True}" + chr(10))
_s.__stderr__.flush()
"""

DISPATCH = """(code) => {
  const m = window.fcInstance;
  if (!m || !m._fcweb_run_python) return 'no-bridge';
  const n = new TextEncoder().encode(code).length + 1;
  const q = m._malloc(n);
  m.stringToUTF8(code, q, n);
  (window.fcRunPy || function (mm, pp) { mm._fcweb_run_python(pp); mm._free(pp); })(m, q);
  return 'dispatched';
}"""

GL_ARGS = {
    'swiftshader': ['--use-gl=angle', '--use-angle=swiftshader',
                    '--enable-unsafe-swiftshader'],
    'angle': ['--use-gl=angle'],
    'egl': ['--use-gl=egl'],
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('directory')
    ap.add_argument('port', type=int)
    ap.add_argument('--gl', default='swiftshader', choices=sorted(GL_ARGS))
    ap.add_argument('--boot-timeout', type=int, default=600)
    ap.add_argument('--shot', default=None)
    args = ap.parse_args()

    from playwright.sync_api import sync_playwright
    from PIL import Image

    here = os.path.dirname(os.path.abspath(__file__))
    repo = os.environ.get('FCWEB_REPO', os.getcwd())
    server = subprocess.Popen(
        [sys.executable, os.path.join(repo, 'tools', 'serve-artifact.py'),
         args.directory, str(args.port)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1.5)
    profile = tempfile.mkdtemp(prefix='fcpix-')
    rc = 1
    try:
        with sync_playwright() as pw:
            ctx = pw.chromium.launch_persistent_context(
                profile, headless=True,
                args=['--enable-features=WebAssemblyJavaScriptPromiseIntegration',
                      '--js-flags=--experimental-wasm-jspi',
                      '--disable-dev-shm-usage', '--no-sandbox',
                      '--window-size=1280,900'] + GL_ARGS[args.gl],
                viewport={'width': 1280, 'height': 900})
            page = ctx.new_page()
            page.add_init_script(CAPTURE)
            page.goto('http://127.0.0.1:%d/index.html' % args.port, timeout=120_000)
            print('gl mode: %s' % args.gl)
            print('context: %s' % (page.evaluate(GL_INFO),))

            t0 = time.time()
            while time.time() - t0 < args.boot_timeout:
                try:
                    if page.evaluate('!!window.__fcAppReady'):
                        break
                except Exception:
                    pass
                time.sleep(2)
            else:
                print('never reached Ready')
                return 1
            print('ready in %.0fs, rAF ticks so far: %s'
                  % (time.time() - t0, page.evaluate('window.__RAF')))

            r0 = page.evaluate('window.__RAF')
            time.sleep(3)
            r1 = page.evaluate('window.__RAF')
            print('rAF ticks in 3s: %d' % (r1 - r0))

            if page.evaluate(DISPATCH, BOX_PY) == 'no-bridge':
                print('no python bridge')
                return 1

            # The loading overlay is very nearly black, so screenshotting through it looks
            # exactly like a viewport that rendered nothing. Wait for it to go, and hurry
            # it along if the shell's own trigger has not fired.
            for _ in range(30):
                st = page.evaluate("(() => { const l = document.getElementById('load');"
                                   "  return l ? getComputedStyle(l).display : 'gone'; })()")
                if st in ('none', 'gone'):
                    break
                time.sleep(2)
            else:
                page.evaluate("(() => { const l = document.getElementById('load');"
                              "  if (l) l.style.display = 'none'; })()")
                print('overlay did not hide on its own; forced it')
            time.sleep(8)

            shot = args.shot or os.path.join(here, 'pixels.png')
            page.screenshot(path=shot)
            im = Image.open(shot).convert('RGB')
            colours = {}
            w, h = im.size
            for y in range(0, h, 3):
                for x in range(0, w, 3):
                    p = im.getpixel((x, y))
                    colours[p] = colours.get(p, 0) + 1
            total = sum(colours.values())
            top = sorted(colours.items(), key=lambda kv: -kv[1])[:4]
            print('screenshot %dx%d, %d distinct colours sampled' % (w, h, len(colours)))
            for c, n in top:
                print('   %-18s %5.1f%%' % (str(c), 100.0 * n / total))
            print('saved %s' % shot)
            rc = 0
            ctx.close()
    finally:
        server.terminate()
        import shutil
        shutil.rmtree(profile, ignore_errors=True)
    return rc


if __name__ == '__main__':
    sys.exit(main())
