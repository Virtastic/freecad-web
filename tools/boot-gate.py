# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) Virtastic
"""Start the built application in a real browser and make it do CAD work. Fail if it cannot.

    python tools/boot-gate.py <dir>                       # boot + geometry
    python tools/boot-gate.py <dir> --scenario restore     # + save, reload, restore
    python tools/boot-gate.py <dir> --scenario all --expect-version 1.1.3

THE GAP THIS CLOSES

For the whole of the 1.1.3 port the application could not start, and every gate was green.
CI compiled it, linked it, validated the wasm, checked the GL patch table, checked the
exception model, counted archive symbols, and deployed -- without ever running the program.
The bug was found because a person opened the page. Worse, the fix for it had been written
in an earlier session behind `#ifdef FCWEB_REAL_CPYTHON`, a macro defined nowhere in the
repository, so it was inert for months and nothing noticed.

So this gate does the one thing none of the others did: it runs the thing.

SCENARIO boot
  1. the page reaches Ready (window.__fcAppReady, set from Qt's onLoaded, i.e. after
     main() has initialised the interpreter);
  2. no Fatal Python error, no Aborted(), no wasm trap;
  3. FreeCAD's own Python builds real geometry: a Part::Box 10x20x30 must recompute to
     volume 6000.0 with 8 vertices and 6 faces -- interpreter, bindings and OCCT kernel
     together, which is exactly what the boot bug broke;
  4. App.Version() is the version we think we shipped;
  5. all of it inside a time budget, because a hang is a failure and not a wait.

SCENARIO restore -- the half a fresh profile can never test
  A new browser profile has no saved work, so scenario `boot` never exercises the restore
  path at all. That path is where a returning user's documents come back, and it is where
  a null-function trap in QEventLoop::exit was seen by hand. This scenario keeps ONE
  browser profile across two loads: make a document, wait for autosave to write it and for
  IDBFS to persist it, then load again and require that the app says it restored the work
  and that no trap fired. It also proves autosave installed at all -- which is how ?no3d
  was caught silently disabling it.

The 3D viewport is off by default (?no3d). Headless GL is not the GL a user has, so a
rendering verdict from here would look like coverage while proving something else;
rendering stays a human check (RELEASE-PLAN.md V6). Pass --with-3d to override.
"""
import argparse
import ast
import os
import re
import shutil
import subprocess
import sys
import tempfile
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

MAKE_DOC_PY = r'''
import FreeCAD as App, sys as _s
_d = App.newDocument("RestoreProbe")
_b = _d.addObject("Part::Box", "Box")
_b.Length = 12; _b.Width = 8; _b.Height = 5
_d.recompute()
_d.saveAs("/home/web_user/RestoreProbe.FCStd")
_s.__stderr__.write("FCMADE ok\n")
_s.__stderr__.flush()
'''

DIALOG_PY = r'''
# Prompt-driven workflows are a whole class of feature: anything that asks for a name, a
# count or a length. A stub here once made every one of them take the cancel branch and
# quietly do nothing, so drive a real modal and require the typed value back.
import sys as _s
try:
    from PySide6 import QtWidgets, QtCore

    def _accept():
        dlg = QtWidgets.QApplication.activeModalWidget()
        if dlg is None:
            _s.__stderr__.write("FCDIALOG {'ok': False, 'why': 'no modal appeared'}\n")
            _s.__stderr__.flush()
            return
        for e in dlg.findChildren(QtWidgets.QLineEdit):
            e.setText("typed-by-gate")
        dlg.accept()

    QtCore.QTimer.singleShot(1500, _accept)
    _v, _ok = QtWidgets.QInputDialog.getText(None, "gate", "Name:")
    _s.__stderr__.write("FCDIALOG " + repr({"ok": bool(_ok), "value": _v}) + "\n")
    _s.__stderr__.flush()
except Exception as _e:
    _s.__stderr__.write("FCDIALOG " + repr({"ok": False, "why": repr(_e)}) + "\n")
    _s.__stderr__.flush()
'''

COUNT_DOCS_PY = r'''
import FreeCAD as App, sys as _s
_names = list(App.listDocuments().keys())
_vol = -1.0
for _n in _names:
    for _o in App.getDocument(_n).Objects:
        if getattr(_o, "TypeId", "") == "Part::Box":
            _vol = _o.Shape.Volume
_s.__stderr__.write("FCDOCS " + repr({"docs": _names, "boxVolume": _vol}) + "\n")
_s.__stderr__.flush()
'''

# Any of these in the output means the engine died, whatever else it printed.
FATAL = re.compile(
    r'Fatal Python error|Aborted\(\)|RuntimeError: unreachable|null function|'
    r'_PyThreadState_Attach|failed to initialize importlib|memory access out of bounds',
    re.I)

# The shell routes the engine's stdout/stderr into its own DOM log, not the console, so a
# console-only gate would miss both the smoke result AND any Python fatal. Every line does
# pass through window.fcwebLogRing, so define that as a property BEFORE the page loads:
# whatever the shell later assigns gets wrapped rather than replaced. The gate then sees
# every line while testing the SHIPPED page rather than a modified copy.
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

AUTOSAVE_DIR_JS = """() => {
  try {
    return window.fcInstance.FS.readdir('/home/web_user/.fcweb-autosave')
             .filter(x => x !== '.' && x !== '..');
  } catch (e) { return null; }
}"""

CHROME_ARGS = [
    # JSPI: the port suspends across JS boundaries (dialogs, long restores). Without it
    # the engine loads and then traps the first time it yields.
    '--enable-features=WebAssemblyJavaScriptPromiseIntegration',
    '--js-flags=--experimental-wasm-jspi',
    # A 182 MB module plus a 145 MB preload needs more than the default headless limits,
    # and an OOM here would read as an engine fault.
    '--disable-dev-shm-usage',
    '--no-sandbox',
]


class Session:
    """One page load, with both output channels and the python bridge."""

    def __init__(self, ctx, url, timeout):
        self.console = []
        self.page = ctx.new_page()
        self.page.add_init_script(CAPTURE_JS)
        self.page.on('console', lambda m: self.console.append('%s %s' % (m.type, m.text)))
        self.page.on('pageerror', lambda e: self.console.append('pageerror %s' % e))
        self.url = url
        self.timeout = timeout
        self.elapsed = None
        self.ready = False

    def lines(self):
        try:
            return self.console + self.page.evaluate('window.__GATE || []')
        except Exception:
            return self.console

    def errors(self):
        try:
            return self.page.evaluate('window.__ERRS || []')
        except Exception:
            return []

    def fatals(self):
        return [c for c in self.lines() if FATAL.search(c)]

    def load(self):
        t0 = time.time()
        self.page.goto(self.url, timeout=120_000)
        while time.time() - t0 < self.timeout:
            if self.fatals():
                break
            try:
                if self.page.evaluate('!!window.__fcAppReady'):
                    self.ready = True
                    break
            except Exception:
                pass            # navigation/teardown races are not verdicts
            time.sleep(2)
        self.elapsed = time.time() - t0
        return self.ready

    def phase(self):
        """Whatever the overlay last said -- 'never reached Ready' alone just sends the
        next person hunting."""
        try:
            return self.page.evaluate(
                """() => {
                     const s = document.getElementById('ld-status');
                     const d = document.getElementById('ld-detail');
                     return (s ? s.textContent : '?') + ' / ' + (d ? d.textContent : '');
                   }""").strip()[:160]
        except Exception:
            return 'unknown'

    def run_python(self, code):
        return self.page.evaluate(DISPATCH_JS, code)

    def wait_for(self, marker, seconds):
        deadline = time.time() + seconds
        while time.time() < deadline:
            for c in self.lines():
                m = re.search(re.escape(marker) + r' (\{.*\})', c)
                if m:
                    # The probes emit repr(dict), so parse it as a Python literal. JSON
                    # cannot: Python writes True, not true, and a dialog result is mostly
                    # booleans.
                    return ast.literal_eval(m.group(1))
                if marker in c:
                    return True
            time.sleep(2)
        return None


def scenario_boot(ctx, url, args, fail):
    s = Session(ctx, url, args.timeout)
    if not s.load():
        fail('never reached Ready in %ds (overlay last said: %s)' % (args.timeout, s.phase()))
    else:
        print('==> Ready in %.0fs' % s.elapsed)
    for f in s.fatals():
        fail('engine reported a fatal: %s' % f[:300])
        break

    if s.ready and not s.fatals():
        s.run_python(SMOKE_PY)
        r = s.wait_for('FCGATE', 120)
        if not isinstance(r, dict):
            fail('the Part::Box smoke test produced no result in 120s')
        else:
            print('==> geometry: %s' % r)
            if abs(r['volume'] - 6000.0) > 1e-6:
                fail('box volume is %r, expected 6000.0' % r['volume'])
            if r['verts'] != 8 or r['faces'] != 6:
                fail('box topology is %d verts / %d faces, expected 8/6'
                     % (r['verts'], r['faces']))
            if args.expect_version and r['version'] != args.expect_version:
                fail('App.Version() is %s, expected %s' % (r['version'], args.expect_version))
        for f in s.fatals():
            fail('engine reported a fatal while working: %s' % f[:300])
            break
    return s


def scenario_restore(ctx, url, args, fail):
    """Two loads, one profile: the returning-user path a fresh profile cannot reach."""
    s1 = Session(ctx, url, args.timeout)
    if not s1.load():
        fail('restore pass 1: never reached Ready (overlay: %s)' % s1.phase())
        return s1
    s1.run_python(MAKE_DOC_PY)
    if not s1.wait_for('FCMADE', 120):
        fail('restore pass 1: the document was never saved')
        return s1

    # Autosave has to install, write a copy, and IDBFS has to persist it. Wait on each
    # step rather than sleeping and hoping -- a test that guesses proves nothing.
    if not s1.wait_for('[autosave] observer installed', 120):
        fail('autosave never installed, so nothing would be restored '
             '(this is how ?no3d was caught disabling it)')
        return s1
    listing = None
    deadline = time.time() + 90
    while time.time() < deadline:
        listing = s1.page.evaluate(AUTOSAVE_DIR_JS)
        if listing:
            break
        time.sleep(2)
    if not listing:
        fail('autosave installed but wrote nothing to .fcweb-autosave in 90s')
        return s1
    print('==> autosaved: %s' % listing)
    time.sleep(25)          # the IDBFS persist backstop runs every 15s
    s1.page.close()

    s2 = Session(ctx, url, args.timeout)
    if not s2.load():
        fail('restore pass 2: never reached Ready (overlay: %s)' % s2.phase())
        return s2
    if not s2.wait_for('restored', 120):
        fail('pass 2 did not report restoring the previous session -- a returning user '
             'would find their work gone')
    s2.run_python(COUNT_DOCS_PY)
    r = s2.wait_for('FCDOCS', 120)
    if not isinstance(r, dict):
        fail('could not read the restored document list')
    else:
        print('==> restored: %s' % r)
        if not r['docs']:
            fail('no documents came back after the reload')
        if abs(r['boxVolume'] - 480.0) > 1e-6:
            fail('the restored box has volume %r, expected 480.0 (12x8x5) -- the document '
                 'came back but its geometry did not survive' % r['boxVolume'])
    for f in s2.fatals():
        fail('restore path reported a fatal: %s' % f[:300])
        break
    return s2


def scenario_dialog(ctx, url, args, fail):
    """A modal has to open, take input, and give the value back."""
    s = Session(ctx, url, args.timeout)
    if not s.load():
        fail('dialog scenario: never reached Ready (overlay: %s)' % s.phase())
        return s
    s.run_python(DIALOG_PY)
    r = s.wait_for('FCDIALOG', 120)
    if not isinstance(r, dict):
        fail('QInputDialog never returned -- a blocking dialog that does not come back '
             'is worse than one that cancels')
    elif not r.get('ok'):
        fail('QInputDialog reported cancelled (%s) -- every prompt-driven command is '
             'dead' % r.get('why', 'no reason given'))
    elif r.get('value') != 'typed-by-gate':
        fail('QInputDialog returned %r, not what was typed' % r.get('value'))
    else:
        print('==> dialog: value came back intact')
    return s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('directory')
    ap.add_argument('--port', type=int, default=8795)
    ap.add_argument('--timeout', type=int, default=900, help='seconds to reach Ready')
    ap.add_argument('--expect-version', default=None, help='e.g. 1.1.3')
    ap.add_argument('--page', default='index.html')
    ap.add_argument('--scenario', default='boot', choices=('boot', 'restore', 'dialog', 'all'))
    ap.add_argument('--with-3d', action='store_true',
                    help='leave the 3D pipeline on (headless GL proves little; see V6)')
    args = ap.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print('::error::playwright is not installed. pip install playwright && '
              'python -m playwright install chromium', file=sys.stderr)
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

    failures = []
    sessions = []

    def fail(msg):
        failures.append(msg)

    url = 'http://127.0.0.1:%d/%s%s' % (args.port, args.page,
                                        '' if args.with_3d else '?no3d')
    profile = tempfile.mkdtemp(prefix='fcgate-profile-')
    try:
        with sync_playwright() as pw:
            # A persistent context throughout: scenario `restore` needs IndexedDB to
            # survive between loads, and `boot` is unaffected by having one.
            ctx = pw.chromium.launch_persistent_context(profile, headless=True,
                                                        args=CHROME_ARGS)
            print('==> %s (scenario: %s)' % (url, args.scenario))
            if args.scenario in ('boot', 'all'):
                sessions.append(scenario_boot(ctx, url, args, fail))
            if args.scenario in ('restore', 'all'):
                sessions.append(scenario_restore(ctx, url, args, fail))
            if args.scenario in ('dialog', 'all'):
                sessions.append(scenario_dialog(ctx, url, args, fail))
            dump = []
            for s in sessions:
                dump.append((s.lines(), s.console, s.errors()))
            ctx.close()
    finally:
        server.terminate()
        shutil.rmtree(profile, ignore_errors=True)

    if failures:
        for f in failures:
            print('::error::%s' % f)
        for lines, console, errs in dump:
            engine = [c for c in lines if c not in console]
            print('\n--- last 30 lines from the ENGINE ---', file=sys.stderr)
            for c in (engine[-30:] or ['(the engine printed nothing at all)']):
                print(c[:300], file=sys.stderr)
            if errs:
                print('--- page errors ---', file=sys.stderr)
                for e in errs[:5]:
                    print(e[:500], file=sys.stderr)
            print('--- last 15 console lines ---', file=sys.stderr)
            for c in console[-15:]:
                print(c[:300], file=sys.stderr)
        return 1

    # Say what was actually checked. A pass line that claims more than the run covered is
    # how a gate starts being trusted for things it never tested.
    did = {
        'boot': 'starts and does CAD work',
        'restore': 'gives work back after a reload',
        'dialog': 'can ask the user a question and use the answer',
        'all': 'starts, does CAD work, gives work back after a reload, and can ask the '
               'user a question',
    }[args.scenario]
    print('==> boot gate passed: the application %s' % did)
    return 0


if __name__ == '__main__':
    sys.exit(main())
