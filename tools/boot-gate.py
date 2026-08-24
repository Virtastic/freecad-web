# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) Virtastic
"""Start the built application in a real browser and make it do CAD work. Fail if it cannot.

    python tools/boot-gate.py <dir-with-FreeCAD.js/.wasm/.data-and-the-shell>
    python tools/boot-gate.py <dir> --port 8795 --timeout 900 --keep-serving

THE GAP THIS CLOSES

For the whole of the 1.1.3 port the application could not start, and every gate was green.
CI compiled it, linked it, validated the wasm, checked the GL patch table, checked the
exception model, counted archive symbols, and deployed -- without ever running the program.
The bug was found because a person opened the page. Worse, the fix for it had been written
in an earlier session behind `#ifdef FCWEB_REAL_CPYTHON`, a macro defined nowhere in the
repository, so it was inert for months and nothing noticed.

So this gate does the one thing none of the others did: it runs the thing.

WHAT IT ASSERTS

  1. the page reaches Ready (window.__fcAppReady, which the shell sets from Qt's onLoaded,
     i.e. after main() has initialised the interpreter);
  2. no Fatal Python error, no Aborted(), no wasm trap anywhere in the console;
  3. FreeCAD's own Python builds real geometry: a Part::Box 10x20x30 must recompute to
     volume 6000.0 with 8 vertices and 6 faces -- this exercises the interpreter, the
     binding layer and the OCCT kernel together, which is what the boot bug broke;
  4. App.Version() is the version we think we shipped;
  5. all of it inside a time budget, because a hang is a failure and not a wait.

The 3D viewport is deliberately disabled (?no3d, honoured by pre-gui.js). Headless
Chromium's GL is not the GL a user has, so a rendering verdict from here would be worth
less than nothing -- it would look like coverage while proving something else. Rendering is
a separate, human check (see RELEASE-PLAN.md V6).
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time

SMOKE_PY = r'''
import FreeCAD as App, Part, sys as _s
_d = App.newDocument("BootGate")
_b = _d.addObject("Part::Box", "Box")
_b.Length = 10; _b.Width = 20; _b.Height = 30
_d.recompute()
_sh = _b.Shape
_v = App.Version()
_s.__stderr__.write("FCGATE " + repr({
    "volume": _sh.Volume,
    "verts": len(_sh.Vertexes),
    "faces": len(_sh.Faces),
    "version": _v[0] + "." + _v[1] + "." + _v[2],
    "docs": len(App.listDocuments()),
}) + "\n")
_s.__stderr__.flush()
'''

# Anything matching these in console output means the engine died, whatever else it printed.
FATAL = re.compile(
    r'Fatal Python error|Aborted\(\)|RuntimeError: unreachable|null function|'
    r'_PyThreadState_Attach|failed to initialize importlib|memory access out of bounds',
    re.I)

# The shell routes the engine's stdout/stderr into its own DOM log, not the console, so a
# console-only gate would miss both the smoke result AND any Python fatal. Every line does
# pass through window.fcwebLogRing, though, so define that as a property BEFORE the page
# loads: whatever the shell later assigns gets wrapped rather than replaced. The gate then
# sees every line while testing the shipped page exactly as users receive it.
CAPTURE_JS = """
(() => {
  window.__GATE = [];
  let real = null;
  Object.defineProperty(window, 'fcwebLogRing', {
    configurable: true,
    get() {
      return (line) => {
        try { window.__GATE.push(String(line)); } catch (e) {}
        try { if (real) real(line); } catch (e) {}
      };
    },
    set(fn) { real = fn; },
  });
})();
"""

DISPATCH_JS = """(code) => {
  const m = window.fcInstance;
  if (!m || !m._fcweb_run_python) return 'no-bridge';
  const n = new TextEncoder().encode(code).length + 1;
  const q = m._malloc(n);
  m.stringToUTF8(code, q, n);
  (window.fcRunPy || function (mm, pp) { mm._fcweb_run_python(pp); mm._free(pp); })(m, q);
  return 'dispatched';
}"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('directory')
    ap.add_argument('--port', type=int, default=8795)
    ap.add_argument('--timeout', type=int, default=900, help='seconds to reach Ready')
    ap.add_argument('--expect-version', default=None, help='e.g. 1.1.3')
    ap.add_argument('--page', default='index.html')
    args = ap.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print('::error::playwright is not installed. pip install playwright && '
              'playwright install --with-deps chromium', file=sys.stderr)
        return 2

    for f in ('FreeCAD.js', 'FreeCAD.wasm'):
        if not os.path.exists(os.path.join(args.directory, f)):
            print('::error::%s is missing from %s' % (f, args.directory), file=sys.stderr)
            return 2

    here = os.path.dirname(os.path.abspath(__file__))
    server = subprocess.Popen(
        [sys.executable, os.path.join(here, 'serve-artifact.py'), args.directory,
         str(args.port)],
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    time.sleep(1.5)
    if server.poll() is not None:
        print('::error::the static server exited immediately: %s'
              % server.stderr.read().decode('utf-8', 'replace'), file=sys.stderr)
        return 2

    console = []
    all_lines = []
    failures = []
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(args=[
                # JSPI: the port suspends across JS boundaries (dialogs, long restores).
                # Without it the engine loads and then traps the first time it yields.
                '--enable-features=WebAssemblyJavaScriptPromiseIntegration',
                '--js-flags=--experimental-wasm-jspi',
                # A 182 MB module plus a 145 MB preload needs more than the default headless
                # limits, and an OOM here would read as an engine fault.
                '--disable-dev-shm-usage',
                '--no-sandbox',
            ])
            page = browser.new_page()
            page.add_init_script(CAPTURE_JS)
            page.on('console', lambda m: console.append('%s %s' % (m.type, m.text)))
            page.on('pageerror', lambda e: console.append('pageerror %s' % e))

            def lines():
                """Console plus the engine's own output, which the shell keeps out of it."""
                try:
                    return console + page.evaluate('window.__GATE || []')
                except Exception:
                    return console

            url = 'http://127.0.0.1:%d/%s?no3d' % (args.port, args.page)
            print('==> %s' % url)
            t0 = time.time()
            page.goto(url, timeout=120_000)

            # Ready is Qt's onLoaded, which the shell turns into __fcAppReady. Poll rather
            # than wait_for_function so a fatal is reported the moment it appears instead of
            # after the whole timeout expires.
            ready = False
            while time.time() - t0 < args.timeout:
                if any(FATAL.search(c) for c in lines()):
                    break
                try:
                    if page.evaluate('!!window.__fcAppReady'):
                        ready = True
                        break
                except Exception:
                    pass          # navigation/teardown races are not verdicts
                time.sleep(2)

            elapsed = time.time() - t0
            fatals = [c for c in lines() if FATAL.search(c)]
            if fatals:
                failures.append('engine reported a fatal: %s' % fatals[0][:300])
            if not ready:
                # "Never reached Ready" alone sends the next person hunting. The overlay knows
                # which phase it stopped in, so say so.
                where = ''
                try:
                    where = page.evaluate("""() => {
                         const s = document.getElementById('ld-status');
                         const d = document.getElementById('ld-detail');
                         return (s ? s.textContent : '?') + ' / ' + (d ? d.textContent : '');
                       }""")
                except Exception:
                    pass
                failures.append('never reached Ready in %ds (overlay last said: %s)'
                                % (args.timeout, (where or 'nothing').strip()[:160]))
            else:
                print('==> Ready in %.0fs' % elapsed)

            if ready and not fatals:
                page.evaluate(DISPATCH_JS, SMOKE_PY)
                got = None
                deadline = time.time() + 120
                while time.time() < deadline:
                    for c in lines():
                        m = re.search(r'FCGATE (\{.*\})', c)
                        if m:
                            got = m.group(1)
                            break
                    if got:
                        break
                    time.sleep(2)

                if not got:
                    failures.append('the Part::Box smoke test produced no result in 120s')
                else:
                    r = json.loads(got.replace("'", '"'))
                    print('==> geometry: %s' % r)
                    if abs(r['volume'] - 6000.0) > 1e-6:
                        failures.append('box volume is %r, expected 6000.0' % r['volume'])
                    if r['verts'] != 8 or r['faces'] != 6:
                        failures.append('box topology is %d verts / %d faces, expected 8/6'
                                        % (r['verts'], r['faces']))
                    if args.expect_version and r['version'] != args.expect_version:
                        failures.append('App.Version() is %s, expected %s'
                                        % (r['version'], args.expect_version))
                # A fatal can also arrive DURING the smoke test.
                late = [c for c in lines() if FATAL.search(c)]
                if late and not fatals:
                    failures.append('engine reported a fatal while working: %s' % late[0][:300])

            all_lines = lines()
            browser.close()
    finally:
        server.terminate()

    if failures:
        for f in failures:
            print('::error::%s' % f)
        engine = [c for c in all_lines if c not in console]
        print('\n--- last 30 lines from the ENGINE ---', file=sys.stderr)
        for c in (engine[-30:] or ['(the engine printed nothing at all)']):
            print(c[:300], file=sys.stderr)
        print('\n--- last 20 lines from the browser console ---', file=sys.stderr)
        for c in console[-20:]:
            print(c[:300], file=sys.stderr)
        return 1

    print('==> boot gate passed: the application starts and does CAD work')
    return 0


if __name__ == '__main__':
    sys.exit(main())
