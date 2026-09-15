"""Is the app quiet when nothing happens? Wake pumps per second after boot (idle, no input) and
which Qt objects hold timers. usage: idle-pump-probe.py [url]"""
import importlib.util, shutil, sys, tempfile, time
sys.path.insert(0, 'tools')
from playwright.sync_api import sync_playwright
_spec = importlib.util.spec_from_file_location('bg', 'tools/boot-gate.py'); bg = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(bg)
_spec2 = importlib.util.spec_from_file_location('am', 'scratchpad/am-seq-probe.py')
URL = sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:8099/?no3d'
TIMERS = open('scratchpad/am-seq-probe.py').read().split('TIMERS = ')[1].split('profile = ')[0]
TIMERS = eval(TIMERS.strip())
EVF = chr(10).join([
    "import sys as _s",
    "from PySide6 import QtCore, QtWidgets",
    "class _EF(QtCore.QObject):",
    "    n = {}",
    "    def eventFilter(self, o, e):",
    "        k = str(e.type()).replace('Type.', '') + ' ' + o.metaObject().className(); self.n[k] = self.n.get(k, 0) + 1",
    "        return False",
    "app = QtWidgets.QApplication.instance(); app._ef = _EF(); app.installEventFilter(app._ef)",
    "def _dump():",
    "    app.removeEventFilter(app._ef); top = sorted(app._ef.n.items(), key=lambda kv: -kv[1])[:25]",
    "    _s.__stderr__.write('FCEVF ' + repr(top) + chr(10)); _s.__stderr__.flush()",
    "QtCore.QTimer.singleShot(5000, _dump)", ""])
profile = tempfile.mkdtemp(prefix='fcidle-')
with sync_playwright() as pw:
    ctx = pw.chromium.launch_persistent_context(profile, headless=True, args=bg.CHROME_ARGS, viewport={'width': 1600, 'height': 900})
    s = bg.Session(ctx, URL, 600)
    assert s.load(), 'boot'
    time.sleep(15)
    def st(): return s.page.evaluate('JSON.stringify({wake: window.__fcQtWake|0, wakePumps: window.__fcWakePumps|0, pumped: window.__fcPumped|0, ms: window.__fcPumpMs|0, t: performance.now(), hooked: !!(window.fcInstance && window.fcInstance.__fcQtWakeHooked), state: window.__fcPumpState && window.__fcPumpState(), err: window.__fcPumpErr, ready: !!window.__fcAppReady, live: Object.keys(window.__qtT ? window.__qtT.live : {}).length, fired: window.__qtT && window.__qtT.fired})')
    INSTR = open('scratchpad/am-seq-probe.py').read().split('INSTR = ')[1].split(chr(10))[0]
    print('==> instr', s.page.evaluate(eval(INSTR)))
    print('==> state', st())
    s.run_python('import FreeCADGui; FreeCADGui.updateGui()'); time.sleep(2)
    print('==> after a manual updateGui', st())
    s.run_python(EVF); a = st(); time.sleep(10); b = st(); ev = [l for l in s.lines() if 'FCEVF' in l]; print('==> events in 5 s', ev[-1][:1500] if ev else None)
    import json; A, B = json.loads(a), json.loads(b)
    print('==> idle 10 s: wakes %d, wake pumps %d, pumps %d, pump time %d ms (%.1f%% of wall)' % (B['wake'] - A['wake'], B['wakePumps'] - A['wakePumps'], B['pumped'] - A['pumped'], B['ms'] - A['ms'], 100.0 * (B['ms'] - A['ms']) / (B['t'] - A['t'])))
    s.run_python(TIMERS); time.sleep(3)
    tl = [l for l in s.lines() if 'FCTIMERS' in l]; print('==> timers', tl[-1][:1500] if tl else None)
    ctx.close()
shutil.rmtree(profile, ignore_errors=True)
