"""The Addon Manager flake in the FULL gate: standalone `--scenario addonmgr` passes 3/3, the
`all` sequence fails it every time the page boots with a restored session AND an installed
addon (FreeCAD-macros-master). Reproduce that state with the gate's own Session/probes on a
persistent profile, then watch what the engine is doing while FCADDONMGR never arrives:
bridge state, Qt timer liveness (a separate Python call on a timer) and the AM command's own
startup_sequence, every 10 s."""
import importlib.util, json, os, shutil, sys, tempfile, time
sys.path.insert(0, 'tools')
from playwright.sync_api import sync_playwright
_spec = importlib.util.spec_from_file_location('bg', 'tools/boot-gate.py'); bg = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(bg)

URL = sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:8099/?no3d'
PING = "\n".join([
    "import sys as _s, AddonManager, FreeCAD",
    "cmd = getattr(AddonManager, '_fcweb_cmd', None)",
    "seq = [getattr(f, '__name__', str(f)) for f in getattr(cmd, 'startup_sequence', [])] if cmd else None",
    "model = getattr(cmd, 'item_model', None) if cmd else None",
    "dlg = getattr(cmd, 'dialog', None) if cmd else None",
    "_s.__stderr__.write('FCAMPING ' + repr({'cmd': cmd is not None, 'seq': seq, 'model': model is not None, 'repos': len(model.repos) if model is not None else None, 'dlgVisible': (dlg.isVisible() if dlg else None), 'docs': list(FreeCAD.listDocuments())}) + chr(10))",
    "_s.__stderr__.flush()", ""])
TIMER = "\n".join([
    "import sys as _s",
    "from PySide6 import QtCore",
    "_n = {'t': 0}",
    "def _tk():",
    "    _n['t'] += 1",
    "    if _n['t'] % 5 == 0: _s.__stderr__.write('FCTIMER %d' % _n['t'] + chr(10)); _s.__stderr__.flush()",
    "_t = QtCore.QTimer(); _t.timeout.connect(_tk); _t.start(1000); globals()['_fc_liveness_timer'] = _t", ""])

TIMERS = chr(10).join([
    "import sys as _s, gc",
    "from PySide6 import QtCore, QtWidgets",
    "d = QtCore.QAbstractEventDispatcher.instance(); out = []",
    "seen = set()",
    "def walk(o):",
    "    if id(o) in seen: return",
    "    seen.add(id(o))",
    "    try:",
    "        ts = d.registeredTimers(o)",
    "    except Exception: ts = []",
    "    if ts:",
    "        who = []",
    "        for r in gc.get_referrers(o):",
    "            if isinstance(r, dict):",
    "                ks = [k for k, v in r.items() if v is o]",
    "                if ks: who.append((r.get('__name__', '?') if '__name__' in r else '', ks))",
    "        out.append((o.metaObject().className(), [(t.timerId, t.interval, str(t.timerType)) if hasattr(t, 'timerId') else str(t) for t in ts], who[:3]))",
    "    for c in o.children(): walk(c)",
    "app = QtWidgets.QApplication.instance(); walk(app)",
    "for w in QtWidgets.QApplication.topLevelWidgets(): walk(w)",
    "for o in gc.get_objects():",
    "    if isinstance(o, QtCore.QObject):",
    "        try: walk(o)",
    "        except Exception: pass",
    "_s.__stderr__.write('FCTIMERS ' + repr(out)[:3000] + chr(10)); _s.__stderr__.flush()", ""])
profile = tempfile.mkdtemp(prefix='fcamseq-')
class A: pass
args = A(); args.timeout = 600
with sync_playwright() as pw:
    ctx = pw.chromium.launch_persistent_context(profile, headless=True, args=bg.CHROME_ARGS, viewport={'width': 1600, 'height': 900})
    s1 = bg.Session(ctx, URL, 600)
    assert s1.load(), 'boot'
    # two documents to be restored next boot (the gate's sessions leave RestoreProbe + SaveProbe behind)
    s1.run_python("import FreeCAD, Part\nfor n in ('SeqProbeA', 'SeqProbeB'):\n    d = FreeCAD.newDocument(n); d.addObject('Part::Box', 'Box'); d.recompute()\nimport sys; sys.__stderr__.write('FCSEQDOCS {}' + chr(10))\n")
    print('==> docs', s1.wait_for('FCSEQDOCS', 60), flush=True)
    s1.run_python(bg.ADDON_INSTALL_PY)
    print('==> install', s1.wait_for('FCADDONINSTALL', 300), flush=True)
    time.sleep(6)   # autosave + IDBFS flush
    s1.page.evaluate("() => new Promise(r => window.fcInstance.fcwebSyncFS ? window.fcInstance.fcwebSyncFS(() => r(1)) : r(0))")
    s1.page.close()
    s2 = bg.Session(ctx, URL, 600)
    assert s2.load(), 'boot 2'
    INSTR = "(() => { const m = window.fcInstance, c = m.qtSuspendResumeControl; const T = window.__qtT = {asyncify: c.asyncifyEnabled, set: 0, fired: 0, cleared: 0, live: {}, lastFire: null, dispatched: 0}; const isQt = f => Object.values(c.eventHandlers).includes(f); const oS = window.setTimeout, oC = window.clearTimeout; window.setTimeout = function (f, ms) { if (typeof f === 'function' && isQt(f)) { T.set++; const idx = Object.keys(c.eventHandlers).find(k => c.eventHandlers[k] === f); const id = oS.call(window, function () { T.fired++; delete T.live[id]; T.byIdx = T.byIdx || {}; T.byIdx[idx] = (T.byIdx[idx] || 0) + 1; T.lastFire = {idx, ms, pending: c.pendingEvents.length, resume: !!c.resume, excl: c.exclusiveEventHandler, t: Math.round(performance.now())}; return f.apply(this, arguments); }, ms); T.live[id] = {idx, ms, t: Math.round(performance.now())}; return id; } return oS.apply(window, arguments); }; window.clearTimeout = function (id) { if (T.live[id]) { T.cleared++; delete T.live[id]; } return oC.apply(window, arguments); }; const oQ = m.qtSendPendingEvents; if (oQ) m.qtSendPendingEvents = function () { T.dispatched++; return oQ.apply(this, arguments); }; return JSON.stringify({asyncify: T.asyncify, handlers: Object.keys(c.eventHandlers).length}); })()"
    print('==> instr', s2.page.evaluate(INSTR), flush=True); s2.page.evaluate('(function f(){ window.__rafN = (window.__rafN|0)+1; requestAnimationFrame(f); })()')
    time.sleep(8)
    print('==> qtT after 8 s idle', s2.page.evaluate('JSON.stringify(window.__qtT)'), flush=True)
    s2.run_python(TIMER); time.sleep(1)
    s2.run_python(bg.ADDONMGR_OPEN_PY)
    t0 = time.time(); seen = None
    while time.time() - t0 < 40:
        time.sleep(10)
        lines = s2.lines()
        r = [l for l in lines if 'FCADDONMGR' in l]
        timers = [l for l in lines if 'FCTIMER' in l]
        s2.run_python(PING); time.sleep(3)
        pings = [l for l in s2.lines() if 'FCAMPING' in l]
        print('==> t+%3.0fs bridge=%s timerTicks=%s qtT=%s ping=%s' % (time.time() - t0, s2.bridge_state(), timers[-1][-12:] if timers else None, s2.page.evaluate('JSON.stringify(window.__qtT)'), pings[-1][:300] if pings else None), flush=True)
        print('    pump', s2.page.evaluate('JSON.stringify({wake: window.__fcQtWake, wakePumps: window.__fcWakePumps, pumped: window.__fcPumped, state: window.__fcPumpState && window.__fcPumpState(), ready: window.__fcAppReady, raf: (window.__rafN|0)})'), flush=True)
        if r:
            print('==> REPORT', r[-1][:300])
            s2.run_python(TIMERS); time.sleep(3); tl = [l for l in s2.lines() if 'FCTIMERS' in l]; print('==> TIMERS', tl[-1][:3000] if tl else None); break
    eng = [l for l in s2.lines() if not l.startswith(('log ', 'warning ', 'error '))]
    print('==> last engine lines:'); [print('   ', l[:200]) for l in eng[-25:]]
    ctx.close()
shutil.rmtree(profile, ignore_errors=True)
