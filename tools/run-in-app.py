# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) Virtastic
"""Boot the built application headless and run a Python file inside it.

    python tools/run-in-app.py <serve-dir> <script.py>
    python tools/run-in-app.py <serve-dir> <script.py> --with-3d --wait 60

Prints everything the engine writes while the script runs, so a claim about what
FreeCAD-in-the-browser does can be settled by running it rather than by reading the
source and reasoning about it. The boot gate answers "does it work"; this answers
"what happens if I do X", which is what most of RELEASE-PLAN.md actually needs.

Write to sys.__stderr__ from the script: FreeCAD redirects sys.stderr into its own
Report view, which never reaches the page.
"""
import argparse
import io
import os
import subprocess
import sys
import tempfile
import time

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
  window.__ERRS = [];
  window.addEventListener('error', (e) => {
    try { window.__ERRS.push(String(e.message) + ' :: ' + ((e.error && e.error.stack) || '')); }
    catch (_) {}
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
    ap.add_argument('script')
    ap.add_argument('--port', type=int, default=8830)
    ap.add_argument('--boot-timeout', type=int, default=600)
    ap.add_argument('--wait', type=int, default=45, help='seconds to watch after dispatch')
    ap.add_argument('--with-3d', action='store_true')
    ap.add_argument('--page', default='index.html')
    args = ap.parse_args()

    code = io.open(args.script, encoding='utf-8').read()

    from playwright.sync_api import sync_playwright

    here = os.path.dirname(os.path.abspath(__file__))
    server = subprocess.Popen(
        [sys.executable, os.path.join(here, 'serve-artifact.py'), args.directory,
         str(args.port)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1.5)
    profile = tempfile.mkdtemp(prefix='fcrun-')
    rc = 0
    try:
        with sync_playwright() as pw:
            ctx = pw.chromium.launch_persistent_context(profile, headless=True, args=[
                '--enable-features=WebAssemblyJavaScriptPromiseIntegration',
                '--js-flags=--experimental-wasm-jspi',
                '--disable-dev-shm-usage', '--no-sandbox'])
            page = ctx.new_page()
            page.add_init_script(CAPTURE_JS)
            console = []
            page.on('console', lambda m: console.append('%s %s' % (m.type, m.text)))
            url = 'http://127.0.0.1:%d/%s%s' % (args.port, args.page,
                                                '' if args.with_3d else '?no3d')
            page.goto(url, timeout=120_000)
            t0 = time.time()
            while time.time() - t0 < args.boot_timeout:
                try:
                    if page.evaluate('!!window.__fcAppReady'):
                        break
                except Exception:
                    pass
                time.sleep(2)
            else:
                print('::error::never reached Ready', file=sys.stderr)
                return 1
            print('==> ready in %.0fs, running %s' % (time.time() - t0, args.script))

            before = len(page.evaluate('window.__GATE || []'))
            if page.evaluate(DISPATCH_JS, code) == 'no-bridge':
                print('::error::the python bridge is not exported', file=sys.stderr)
                return 1

            deadline = time.time() + args.wait
            seen = before
            while time.time() < deadline:
                lines = page.evaluate('window.__GATE || []')
                for l in lines[seen:]:
                    print('   %s' % l[:400])
                seen = len(lines)
                time.sleep(2)
            errs = page.evaluate('window.__ERRS || []')
            if errs:
                print('--- page errors ---')
                for e in errs[:5]:
                    print('   %s' % e[:400])
                    rc = 1
            ctx.close()
    finally:
        server.terminate()
        import shutil
        shutil.rmtree(profile, ignore_errors=True)
    return rc


if __name__ == '__main__':
    sys.exit(main())
